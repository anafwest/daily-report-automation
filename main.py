import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from scripts import admin_report, capture, crm_capture, export_excel, login, run_log, send_email, split_by_dept, summarize, validate_report
from scripts.config_loader import BASE_DIR, load_config
from scripts.scheduler import install as sched_install
from scripts.scheduler import status as sched_status
from scripts.scheduler import uninstall as sched_uninstall
from scripts.split_by_dept import apply_filters

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


_EXCLUDE_PREFIXES = ("ملخص", "سجل", "إدارات", "إدارات", "Unassigned", "crm_", "login_")

# أسماء ملفات العينة التي يولّدها أمر test-send — يجب ألا تُعتمد كتقرير يومي
_TEST_MARKERS = ("تجريبي", "تجربة", "عينة", "test", "sample")


def _report_date_from_name(path: Path):
    """يستخرج تاريخ التقرير (YYYY-MM-DD) من اسم الملف، وإلا None."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%Y-%m-%d").date()
    except ValueError:
        return None


def _find_latest_report(max_age_days: int = 0):
    """أحدث تقرير مقبول للإرسال.

    max_age_days = 0 يعني: تقرير اليوم فقط. أي ملف أقدم أو ملف عينة تجريبي
    يُستبعد ولا يُرسل — لأن إرسال بيان قديم للإدارات أسوأ من عدم الإرسال.
    """
    cfg = load_config()
    out_dir = BASE_DIR / cfg["report"]["download_dir"]
    if not out_dir.exists():
        print(f"مجلد الإخراج غير موجود: {out_dir}")
        return None

    today = datetime.now().date()
    candidates = []
    skipped = []

    for p in out_dir.glob("*.xlsx"):
        if not (p.name.startswith("تقرير_") and any(c.isdigit() for c in p.stem)):
            continue
        if any(p.name.startswith(prefix) for prefix in _EXCLUDE_PREFIXES):
            continue
        if "تقرير_التشغيل" in p.name:
            continue
        if any(marker in p.name for marker in _TEST_MARKERS):
            skipped.append((p.name, "ملف عينة تجريبي (test-send) — لا يُعتمد"))
            continue
        report_date = _report_date_from_name(p)
        if report_date is None:
            skipped.append((p.name, "لا يوجد تاريخ في اسم الملف"))
            continue
        age = (today - report_date).days
        if age < 0 or age > max_age_days:
            skipped.append((p.name, f"تاريخه قبل {age} يوم (الحد المسموح: {max_age_days})"))
            continue
        candidates.append(p)

    for name, why in skipped:
        print(f"  ⏭️ تخطّي «{name}» — {why}")

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None



def _run_daily(source: str, dry_run: bool, headless: bool, test_to: str = "") -> int:
    today = datetime.now()
    weekday = today.weekday()
    if weekday in (4, 5) and not dry_run:
        print(f"⏸️ اليوم {['الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][weekday]} — لا يوجد إرسال أيام الجمعة والسبت.")
        return 0
    start = today
    run_id = run_log.new_run_id()
    summary = {
        "run_id": run_id,
        "date": start.strftime("%Y-%m-%d"),
        "start_time": start.strftime("%H:%M:%S"),
        "end_time": "",
        "status": "fail",
        "failure_stage": "",
        "failure_reason": "",
    }
    result = {}
    failures = []
    validation = {}

    def _fail(stage, reason):
        summary.update(status="fail", failure_stage=stage, failure_reason=reason)
        summary["end_time"] = datetime.now().strftime("%H:%M:%S")
        admin_report.build_admin_report(run_id, summary, result, failures, validation)
        run_log.append_run(summary)
        print(f"\n🔴 فشل التقرير اليومي — المرحلة: {stage} — السبب: {reason}")
        print("لم يتم إرسال أي بريد.")
        # إشعار المسؤول بالفشل — بدونه يبقى العطل صامتاً ولا يعلم به أحد
        try:
            send_email.send_summary_email(summary, dry_run=dry_run, test_to=test_to, result=result)
        except Exception as e:
            print(f"تنبيه: تعذر إرسال إشعار الفشل إلى المسؤول: {e}")
        return 1

    # المرحلة 1: التقرير (التقاط من علاقات العملاء أو ملف جاهز)
    crm_cfg = load_config()["report"].get("crm", {})
    report_path = Path(source) if source else None
    capture_error = ""

    if not source and crm_cfg.get("enabled", True):
        print("بدء الالتقاط من علاقات العملاء...")
        capture_error = ""
        try:
            captured = crm_capture.capture_report(headless=headless)
        except Exception as e:
            captured = ""
            capture_error = str(e)
            print(f"تنبيه: فشل الالتقاط من علاقات العملاء: {e}")
        if captured and Path(captured).exists():
            report_path = Path(captured)
        else:
            capture_error = capture_error or getattr(crm_capture, "LAST_ERROR", "") or "لم يُرجع الالتقاط ملفاً."
            max_age = int(load_config()["report"].get("max_report_age_days", 0))
            print(f"تعذر الالتقاط من علاقات العملاء ({capture_error}) — البحث عن ملف جاهز (حد العمر: {max_age} يوم)...")
            report_path = _find_latest_report(max_age_days=max_age)

    if report_path is None or not report_path.exists():
        if not source:
            return _fail(
                "تحميل التقرير من علاقات العملاء",
                "لم يتم العثور على تقرير مقبول للإرسال (فشل الالتقاط من علاقات العملاء، "
                f"ولا يوجد ملف حديث مطابق). سبب الالتقاط: {capture_error or 'غير محدد'}",
            )
        return _fail("تحميل التقرير", f"الملف غير موجود: {report_path}")


    # المرحلة 2: فحص التقرير
    print("=" * 60)
    print(f"[{run_id}] بدء الدورة اليومية — الملف: {report_path.name}")
    print("=" * 60)
    try:
        df, validation = validate_report.load_report(str(report_path))
    except validate_report.ReportValidationError as e:
        return _fail("فحص التقرير", str(e))
    if validation.get("decision") == "warning":
        print(f"⚠️ {validation['reason']}")
        summary["failure_stage"] = "فحص التقرير"
        summary["failure_reason"] = validation["reason"]
        summary["end_time"] = datetime.now().strftime("%H:%M:%S")
        admin_report.build_admin_report(run_id, summary, result, failures, validation)
        run_log.append_run(summary)
        return 1
    print(f"تقرير سليم: {validation['rows']:,} سجل × {validation['cols']} عمود")

    # تطبيق الفلاتر (الحالة + المنطقة) على البيانات المستخدمة في الإحصائيات والملخص
    filtered_df = apply_filters(df)
    summary["raw_requests"] = int(len(df))
    summary["filtered_out"] = int(len(df) - len(filtered_df))
    summary["total_requests"] = int(len(filtered_df))

    # المرحلة 3: التقسيم
    result = split_by_dept.split_by_department(str(report_path))
    summary["total_depts"] = len(result)
    summary["files_created"] = len(result)
    dept_series = filtered_df[load_config()["report"]["department_column"]]
    empty_depts = dept_series.isna().sum() + (dept_series.astype(str).str.strip() == "").sum()
    summary["unassigned"] = int(empty_depts)
    summary["new_depts"] = sum(1 for i in result.values() if i.get("action") == "new_dept")
    summary["no_email"] = sum(1 for i in result.values() if i.get("action") == "no_email")
    if not result:
        return _fail("التقسيم حسب الإدارة", "لم يتم إنشاء أي ملف إدارة")

    # المرحلة 4: الملخص
    try:
        sum_df = summarize.summarize(filtered_df)
        summarize.save_summary(sum_df)
        print("ملخص الإدارات:")
        print(sum_df.to_string(index=False))
    except Exception as e:
        print(f"تنبيه: تعذر إنشاء الملخص: {e}")

    # المرحلة 5: الإرسال
    email_cfg = load_config()["email"]
    summary_only = bool(email_cfg.get("summary_only", False))
    if summary_only:
        print("📄 وضع الملخص فقط مفعّل — لن تُرسل رسائل الإدارات، يُرسل الملخص للمسؤول فقط.")
        sent, failed = [], []
    else:
        sent, failed = send_email.send_emails(result, dry_run=dry_run, test_to=test_to)
    summary["emails_sent"] = len(sent)
    summary["emails_failed"] = len(failed)
    failures = [(d, r) for d, r in failed]

    # المرحلة 6: الحالة والتقرير والسجل
    # ملاحظة: يجب احتساب الحالة قبل إرسال الملخص — إرساله قبل ذلك كان يجعل
    # نص الملخص يقول "الحالة: فشل" دائماً لأن القيمة الابتدائية لـ status هي "fail".
    if summary["emails_failed"] == 0:
        summary["status"] = "success"
    else:
        summary["status"] = "warning"
    summary["end_time"] = datetime.now().strftime("%H:%M:%S")
    admin_report.build_admin_report(run_id, summary, result, failures, validation)
    run_log.append_run(summary)

    # المرحلة 6.5: إشعار المسؤول (بعد اكتمال الحالة والمؤشرات)
    try:
        send_email.send_summary_email(summary, dry_run=dry_run, test_to=test_to, result=result)
    except Exception as e:
        print(f"تنبيه: تعذر إرسال ملخص المسؤول: {e}")

    if summary["status"] == "success":
        print(f"\n🟢 اكتملت العملية اليومية بنجاح ({run_id})")
    else:
        print(f"\n🟡 اكتملت العملية جزئياً ({run_id}) — إدارات تحتاج متابعة: {len(failures)}")
    if summary_only:
        print(f"📄 [وضع الملخص فقط] — لم تُرسل رسائل الإدارات ({summary['total_depts']} ملف أُنشئ)، الملخص أُرسل للمسؤول فقط.")
    else:
        print(f"الطلبات: {summary['total_requests']:,} | الإدارات: {summary['total_depts']} | البريد: {summary['emails_sent']}/{summary['emails_failed']} | ملخص: تم إرساله")
    print(f"التقرير: {BASE_DIR / load_config()['output']['admin_report_file']}")
    return 0


def cmd_login(args):
    return login.login(auto=not args.manual, inspect=args.inspect, headless=args.headless)


def cmd_capture(args):
    if args.crm:
        file = crm_capture.capture_report(headless=args.headless)
        if file:
            print(f"تم الالتقاط من علاقات العملاء: {file}")
            return 0
        print("تعذر الالتقاط من علاقات العملاء.")
        return 1
    if args.export:
        file = capture.click_export_button(url=args.url, headless=args.headless)
        if file:
            print(f"تم التصدير: {file}")
            return 0
        return 1
    dfs = capture.capture_tables(url=args.url, headless=args.headless)
    if not dfs:
        print("لا توجد بيانات للتصدير.")
        return 1
    cfg = load_config()
    out = BASE_DIR / cfg["output"]["raw_file"]
    export_excel.save_dataframes(dfs, str(out))
    print(f"تم حفظ البيانات الخام في: {out}")
    return 0


def cmd_split(args):
    cfg = load_config()
    source = args.source or BASE_DIR / cfg["output"]["raw_file"]
    result = split_by_dept.split_by_department(str(source), sheet_name=args.sheet)
    print(f"تم تقسيم البيانات إلى {len(result)} إدارة في: {BASE_DIR / cfg['output']['split_dir']}")
    return 0


def cmd_send(args):
    cfg = load_config()
    source = args.source or BASE_DIR / cfg["output"]["raw_file"]
    result = split_by_dept.split_by_department(str(source))
    send_email.send_emails(result, dry_run=args.dry_run, test_to=args.test_to)
    return 0


def cmd_all(args):
    return _run_daily(source=args.source or args.url, dry_run=args.dry_run, headless=args.headless, test_to=args.test_to)


def cmd_run_daily(args):
    return _run_daily(source=args.source, dry_run=args.dry_run, headless=args.headless, test_to=args.test_to)


def cmd_test_send(args):
    from scripts.test_send import run as test_send_run
    return test_send_run(eml=args.eml)


def cmd_report(args):
    cfg = load_config()
    ecfg = cfg["email_list"]
    path = BASE_DIR / ecfg["file"]
    if not path.exists():
        print(f"ملف الإدارات غير موجود: {path}")
        return 1
    import pandas as pd
    df = pd.read_excel(path, dtype=str).fillna("")
    dept_col = ecfg["dept_col"]
    email_col = ecfg["email_col"]
    cc_col = ecfg.get("cc_col", "CC")
    status_col = ecfg.get("status_col", "حالة الإرسال")

    print("=" * 70)
    print(f"  تقرير الإدارات والبريد — إجمالي: {len(df)} إدارة")
    print("=" * 70)
    print(f"{'#':<4} {'الإدارة':<35} {'البريد الإلكتروني':<30} {'الحالة':<10}")
    print("-" * 70)
    for i, (_, row) in enumerate(df.iterrows(), 1):
        dept = str(row.get(dept_col, "")).strip()
        email = str(row.get(email_col, "")).strip()
        status = str(row.get(status_col, "")).strip()
        print(f"{i:<4} {dept:<35} {email:<30} {status:<10}")
    print("-" * 70)

    active = df[df[status_col].astype(str).str.strip().isin(ecfg.get("active_values", ["فعال"]))]
    print(f"\n  فعال: {len(active)} | معطّل: {len(df) - len(active)}")

    if args.xlsx:
        out = BASE_DIR / "output" / "تقرير_الإدارات_والبريد.xlsx"
        from scripts.export_excel import save_dataframes
        save_dataframes([(f"الإدارات ({len(df)})", df)], str(out))
        print(f"  تم حفظ الملف: {out}")

    if args.send:
        from datetime import datetime
        out = BASE_DIR / "output" / "تقرير_الإدارات_والبريد.xlsx"
        if not out.exists():
            from scripts.export_excel import save_dataframes
            save_dataframes([(f"الإدارات ({len(df)})", df)], str(out))
        to = "anaf@alriyadh.gov.sa"
        today = datetime.now().strftime("%d-%m-%Y")
        subject = f"تقرير الإدارات والبريد — {today}"
        body = f"السلام عليكم ورحمة الله وبركاته،\n\nإرفاق تقرير الإدارات والبريد الإلكتروني ({len(df)} إدارة).\n\nمع خالص التحية."
        item = {"to": to, "cc": "", "subject": subject, "body": body, "attachment": str(out)}

        print("\n" + "=" * 50)
        print("  معاينة الإرسال")
        print("=" * 50)
        print(f"  إلى: {to}")
        print(f"  الموضوع: {subject}")
        print(f"  المرفق: {out.name} ({len(df)} إدارة)")
        print("=" * 50)

        if args.dry_run:
            print("  [وضع المعاينة] — لم يتم الإرسال فعلياً")
            return 0

        confirm = input("\n  هل تريد الإرسال الآن؟ (نعم/لا): ").strip()
        if confirm not in ("نعم", "yes", "y", "n", "لا", "ن"):
            print("  تم الإلغاء.")
            return 0

        from scripts.owa_send import send_emails_via_owa
        sent, failed = send_emails_via_owa([item], dry_run=False)
        if sent:
            print(f"  تم إرسال التقرير إلى: {to}")
        elif failed:
            print(f"  فشل الإرسال: {failed}")
            return 1
    return 0


def cmd_schedule(args):
    sched_install() if args.action == "install" else sched_uninstall()
    return 0


def main():
    parser = argparse.ArgumentParser(description="نظام الأتمتة الذكية للتقارير والتوزيع اليومي")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login", help="تسجيل الدخول للبوابة وحفظ الجلسة")
    p.add_argument("--manual", action="store_true")
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("capture", help="التقاط بيانات التقرير من الصفحة")
    p.add_argument("--url", default="")
    p.add_argument("--export", action="store_true")
    p.add_argument("--crm", action="store_true", help="الالتقاط من علاقات العملاء (دخول ADFS + فلتر تاريخ + تصدير)")
    p.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("split", help="تقسيم البيانات حسب الإدارة")
    p.add_argument("--source", default="")
    p.add_argument("--sheet", default=0)
    p.set_defaults(func=cmd_split)

    p = sub.add_parser("send", help="إرسال الإيميلات مع المرفقات")
    p.add_argument("--source", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test-to", default="", help="إرسال تجريبي: كل الرسائل تُحول إلى هذا البريد مع وسم [تجربة]")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("all", help="تنفيذ كل المراحل دفعة واحدة (الوضع القديم)")
    p.add_argument("--source", default="")
    p.add_argument("--url", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--test-to", default="", help="إرسال تجريبي: كل الرسائل تُحول إلى هذا البريد مع وسم [تجربة]")
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("run_daily", help="الدورة اليومية الكاملة وفق مواصفات النظام")
    p.add_argument("--source", default="", help="مسار ملف التقرير الخام (اختياري)")
    p.add_argument("--dry-run", action="store_true", help="معاينة بدون إرسال فعلي")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--test-to", default="", help="إرسال تجريبي: كل الرسائل تُحول إلى هذا البريد مع وسم [تجربة]")
    p.set_defaults(func=cmd_run_daily)

    p = sub.add_parser("test-send", help="دورة تجريبية على بيانات عينة: فحص + فلاتر + تقسيم + معاينة الرسائل")
    p.add_argument("--eml", action="store_true", help="حفظ نسخ .eml من كل رسالة لفتحها في Outlook")
    p.set_defaults(func=cmd_test_send)

    p = sub.add_parser("report", help="عرض تقرير الإدارات والبريد الإلكتروني")
    p.add_argument("--xlsx", action="store_true", help="حفظ التقرير كملف Excel")
    p.add_argument("--send", action="store_true", help="إرسال التقرير إلى anaf@alriyadh.gov.sa عبر OWA")
    p.add_argument("--dry-run", action="store_true", help="معاينة بدون إرسال فعلي")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("schedule", help="جدولة التشغيل اليومي")
    p.add_argument("--action", choices=["install", "uninstall"], default="install")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("schedule-status", help="حالة المهمة المجدولة")
    p.set_defaults(func=lambda args: sched_status())

    import scripts.performance_analysis as _perf
    _perf.add_parser(sub)

    args = parser.parse_args()
    if getattr(args, "cmd", "") == "perf":
        sys.exit(args.perf_fn(args))
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

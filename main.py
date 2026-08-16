import argparse
import sys
from datetime import datetime
from pathlib import Path

from scripts import admin_report, capture, crm_capture, export_excel, login, run_log, send_email, split_by_dept, summarize, validate_report
from scripts.config_loader import BASE_DIR, load_config
from scripts.scheduler import install as sched_install
from scripts.scheduler import status as sched_status
from scripts.scheduler import uninstall as sched_uninstall

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _find_latest_report() -> Path:
    cfg = load_config()
    candidates = sorted(
        (BASE_DIR / cfg["output"]["download_dir"]).glob("*.xlsx"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return candidates[0] if candidates else None


def _run_daily(source: str, dry_run: bool, headless: bool) -> int:
    start = datetime.now()
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
        return 1

    # المرحلة 1: التقرير (ملف جاهز أو التقاط من علاقات العملاء)
    report_path = Path(source) if source else _find_latest_report()
    if report_path is None or not report_path.exists():
        crm_cfg = load_config()["report"].get("crm", {})
        if not source and crm_cfg.get("enabled", True):
            print("لا يوجد ملف تقرير جاهز — بدء الالتقاط من علاقات العملاء...")
            try:
                captured = crm_capture.capture_report(headless=headless)
            except Exception as e:
                captured = ""
                print(f"تنبيه: فشل الالتقاط من علاقات العملاء: {e}")
            if captured and Path(captured).exists():
                report_path = Path(captured)
            else:
                print("تعذر الالتقاط من علاقات العملاء.")
        if report_path is None or not report_path.exists():
            if not source:
                print("لا يوجد ملف تقرير جاهز. حدد المسار بـ --source أو فعّل الالتقاط من علاقات العملاء.")
                summary["failure_stage"] = "تحميل التقرير من علاقات العملاء"
                summary["failure_reason"] = "لم يتم العثور على ملف التقرير أو فشل الالتقاط."
                summary["end_time"] = datetime.now().strftime("%H:%M:%S")
                admin_report.build_admin_report(run_id, summary, result, failures, validation)
                run_log.append_run(summary)
                print("🔴 فشل: لم يتم العثور على ملف التقرير. لم يُرسل أي بريد.")
                return 1
            summary["failure_stage"] = "تحميل التقرير"
            summary["failure_reason"] = f"الملف غير موجود: {report_path}"
            run_log.append_run(summary)
            print(f"🔴 فشل: الملف غير موجود — {report_path}. لم يُرسل أي بريد.")
            return 1

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
    summary["total_requests"] = validation["rows"]

    # المرحلة 3: التقسيم
    result = split_by_dept.split_by_department(str(report_path))
    summary["total_depts"] = len(result)
    summary["files_created"] = len(result)
    dept_series = df[load_config()["report"]["department_column"]]
    empty_depts = dept_series.isna().sum() + (dept_series.astype(str).str.strip() == "").sum()
    summary["unassigned"] = int(empty_depts)
    summary["new_depts"] = sum(1 for i in result.values() if i.get("action") == "new_dept")
    summary["no_email"] = sum(1 for i in result.values() if i.get("action") == "no_email")
    if not result:
        return _fail("التقسيم حسب الإدارة", "لم يتم إنشاء أي ملف إدارة")

    # المرحلة 4: الملخص
    try:
        sum_df = summarize.summarize(df)
        summarize.save_summary(sum_df)
        print("ملخص الإدارات:")
        print(sum_df.to_string(index=False))
    except Exception as e:
        print(f"تنبيه: تعذر إنشاء الملخص: {e}")

    # المرحلة 5: الإرسال
    sent, failed = send_email.send_emails(result, dry_run=dry_run)
    summary["emails_sent"] = len(sent)
    summary["emails_failed"] = len(failed)
    failures = [(d, r) for d, r in failed]

    # المرحلة 6: الحالة والتقرير والسجل
    if summary["emails_failed"] == 0:
        summary["status"] = "success"
    else:
        summary["status"] = "warning"
    summary["end_time"] = datetime.now().strftime("%H:%M:%S")
    admin_report.build_admin_report(run_id, summary, result, failures, validation)
    run_log.append_run(summary)

    if summary["status"] == "success":
        print(f"\n🟢 اكتملت العملية اليومية بنجاح ({run_id})")
    else:
        print(f"\n🟡 اكتملت العملية جزئياً ({run_id}) — إدارات تحتاج متابعة: {len(failures)}")
    print(f"الطلبات: {summary['total_requests']:,} | الإدارات: {summary['total_depts']} | المرسلة: {summary['emails_sent']} | الفاشلة: {summary['emails_failed']}")
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
    send_email.send_emails(result, dry_run=args.dry_run)
    return 0


def cmd_all(args):
    return _run_daily(source=args.source or args.url, dry_run=args.dry_run, headless=args.headless)


def cmd_run_daily(args):
    return _run_daily(source=args.source, dry_run=args.dry_run, headless=args.headless)


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
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("all", help="تنفيذ كل المراحل دفعة واحدة (الوضع القديم)")
    p.add_argument("--source", default="")
    p.add_argument("--url", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("run_daily", help="الدورة اليومية الكاملة وفق مواصفات النظام")
    p.add_argument("--source", default="", help="مسار ملف التقرير الخام (اختياري)")
    p.add_argument("--dry-run", action="store_true", help="معاينة بدون إرسال فعلي")
    p.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd_run_daily)

    p = sub.add_parser("schedule", help="جدولة التشغيل اليومي")
    p.add_argument("--action", choices=["install", "uninstall"], default="install")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("schedule-status", help="حالة المهمة المجدولة")
    p.set_defaults(func=lambda args: sched_status())

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

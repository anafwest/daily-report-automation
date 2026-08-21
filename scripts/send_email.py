import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

from .config_loader import BASE_DIR, env, load_config


def _build_message(sender: str, to: str, cc: str, subject: str, body: str, attachment: str):
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if attachment and Path(attachment).exists():
        with open(attachment, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="xlsx")
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", Path(attachment).name))
        msg.attach(part)
    return msg


def _connect(sender: str, password: str):
    email_cfg = load_config()["email"]
    server = smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"])
    server.ehlo()
    if email_cfg.get("use_tls", True):
        server.starttls()
        server.ehlo()
    server.login(sender, password)
    return server


def _resolve_test_recipient(cfg) -> str:
    """إذا كان وضع الاختبار مفعّلًا في config.json، يرجع البريد الإجباري (كل الرسائل تذهب له فقط)."""
    tm = cfg.get("test_mode", {})
    if tm.get("enabled") and tm.get("force_recipient"):
        return str(tm["force_recipient"]).strip()
    return ""


def send_emails(split_result: dict, dry_run: bool = False, test_to: str = "") -> tuple:
    cfg = load_config()
    email_cfg = cfg["email"]
    sender = env("SMTP_SENDER") or email_cfg.get("sender", "")
    password = env("SMTP_PASSWORD")

    # قفل الاختبار: أي إرسال يتحول إلى البريد المحدد فقط في config.json (test_mode)
    test_to = test_to or _resolve_test_recipient(cfg)
    if test_to:
        print("=" * 60)
        print(f"🧪 وضع التجربة: جميع الرسائل ستُرسل إلى: {test_to} (بدل الإدارات)")
        print("=" * 60)

    if not sender or not password:
        if dry_run:
            sender = sender or "test@example.com"
        else:
            print("لم يتم تعيين SMTP_SENDER أو SMTP_PASSWORD في ملف .env — إرسال فعلي مستحيل.")
            failed = [(d, info.get("reason", "") or "بيانات الإرسال غير مكتملة")
                      for d, info in split_result.items()]
            return [], failed

    today = datetime.now().strftime("%d-%m-%Y")
    sent, failed, blocked = [], [], []

    global_cc = email_cfg.get("global_cc", "")

    ready = []
    for dept, info in split_result.items():
        action = info.get("action", "send")
        to = info.get("email", "")
        if action in ("new_dept", "no_email", "disabled") or not to:
            blocked.append((dept, info.get("reason", "")))
            continue
        dept_cc = info.get("cc", "")
        merged_cc = ",".join(filter(None, [global_cc, dept_cc]))
        subject = email_cfg["subject_template"].format(date=today)
        body = email_cfg["body_template"].format(date=today, count=info.get("rows", 0), dept_name=dept)
        if test_to:
            merged_cc = ""
            orig_to = to
            to = test_to
            subject = f"[تجربة] {subject} — الأصل إلى: {orig_to}"
            body += f"\n\n——————————————\n🧪 رسالة تجريبية — في الوضع العادي ستُرسل هذه الرسالة إلى: {orig_to}"
        ready.append({
            "dept": dept,
            "to": to,
            "cc": merged_cc,
            "subject": subject,
            "body": body,
            "attachment": info.get("file", ""),
        })

    if email_cfg.get("send_via", "smtp") == "owa":
        owa_sent, owa_failed = _send_via_owa(ready, dry_run, sender)
        for e in owa_sent:
            sent.append((e["dept"], e["to"], e.get("cc", ""), e.get("attachment", "")))
        for e in owa_failed:
            failed.append((e.get("dept", ""), "فشل الإرسال عبر OWA"))
        failed += blocked
        _save_summary(sent, failed, blocked, cfg)
        return sent, failed

    if dry_run:
        print("=" * 55)
        print(f"وضع تجربة (بدون إرسال فعلي) - {len(split_result)} إدارة")
        print("=" * 55)
        for e in ready:
            print(f"  [جاهز] {e['dept']} -> {e['to']}" + (f" | CC: {e['cc']}" if e.get("cc") else ""))
            sent.append((e["dept"], e["to"], e.get("cc", ""), e.get("attachment", "")))
        _save_summary(sent, failed, blocked, cfg)
        return sent, failed

    server = None
    try:
        server = _connect(sender, password)
    except Exception as e:
        print(f"تعذر الاتصال بخادم البريد: {e}")
        failed = [(d, f"تعذر الاتصال بالخادم: {e}") for d, info in split_result.items()]
        _save_summary(sent, failed, blocked, cfg)
        return [], failed

    for e in ready:
        msg = _build_message(sender, e["to"], e.get("cc", ""), e["subject"], e["body"], e.get("attachment", ""))
        try:
            server.sendmail(sender, [x for x in [e["to"]] + (e.get("cc", "").split(";") if e.get("cc") else []) if x], msg.as_string())
            print(f"  [أُرسل] {e['dept']} -> {e['to']}")
            sent.append((e["dept"], e["to"], e.get("cc", ""), e.get("attachment", "")))
        except Exception as ex:
            print(f"  [فشل] {e['dept']} -> {e['to']}: {ex}")
            failed.append((e["dept"], str(ex)))

    if server:
        try:
            server.quit()
        except Exception:
            pass

    failed += blocked
    _save_summary(sent, failed, blocked, cfg)
    return sent, failed


def _send_via_owa(ready: list, dry_run: bool, sender: str):
    if not ready:
        return [], []
    if not sender:
        print("لم يتم تعيين SMTP_SENDER (جهة الإرسال) — لا يمكن الإرسال عبر OWA.")
        return [], ready
    from .owa_send import send_emails_via_owa

    return send_emails_via_owa(ready, dry_run=dry_run)


def _save_summary(sent, failed, blocked, cfg):
    summary_path = BASE_DIR / cfg["output"]["summary_file"]
    rows = []
    for d, to, cc, att in sent:
        rows.append({"الإدارة": d, "البريد": to, "CC": cc, "المرفق": Path(att).name if att else "", "الحالة": "أُرسل"})
    for d, reason in failed:
        rows.append({"الإدارة": d, "البريد": "", "CC": "", "المرفق": "", "الحالة": f"فشل: {reason}"})
    for d, reason in blocked:
        rows.append({"الإدارة": d, "البريد": "", "CC": "", "المرفق": "", "الحالة": f"محظور: {reason}"})
    pd.DataFrame(rows).to_excel(summary_path, index=False)
    print(f"الملخص محفوظ في: {summary_path}")


def send_summary_email(summary: dict, dry_run: bool = False, test_to: str = "", result: dict = None) -> bool:
    cfg = load_config()
    email_cfg = cfg["email"]
    sender = env("SMTP_SENDER") or email_cfg.get("sender", "")
    password = env("SMTP_PASSWORD")
    to = email_cfg.get("summary_recipient", "")
    test_to = test_to or _resolve_test_recipient(cfg)
    if test_to:
        to = test_to

    if not to:
        print("لم يتم تعيين summary_recipient في config.json — تخطي إرسال الملخص.")
        return False

    today = summary.get("date", datetime.now().strftime("%Y-%m-%d"))
    status_ar = {"success": "نجاح", "warning": "تنبيه", "fail": "فشل"}.get(summary.get("status", ""), summary.get("status", ""))

    body_lines = [
        f"السلام عليكم ورحمة الله وبركاته",
        "",
        f"تقرير الملاحظات والأخطاء — {today}",
        f"رقم التشغيل: {summary.get('run_id', '')}",
        f"من: {summary.get('start_time', '')} إلى: {summary.get('end_time', '')}",
        "",
        "═" * 50,
        "  ملخص العملية",
        "═" * 50,
        f"  الحالة: {status_ar}",
        f"  الطلبات الإجمالية: {summary.get('raw_requests', 0):,}",
        f"  الطلبات بعد الفلترة: {summary.get('total_requests', 0):,}",
        f"  الطلبات المحذوفة بالفلترة: {summary.get('filtered_out', 0):,}",
        f"  الإدارات: {summary.get('total_depts', 0)}",
        f"  الرسائل المرسلة: {summary.get('emails_sent', 0)}",
        f"  الرسائل الفاشلة: {summary.get('emails_failed', 0)}",
    ]

    if result:
        no_email = [(k, v["rows"]) for k, v in result.items() if not v.get("email") and v.get("action") == "no_email"]
        new_dept = [(k, v["rows"]) for k, v in result.items() if v.get("action") == "new_dept"]
        disabled = [(k, v["rows"]) for k, v in result.items() if v.get("action") == "disabled"]
        failed_list = [(k, v.get("reason", "")) for k, v in result.items() if v.get("action") == "failed"]

        if no_email:
            body_lines += [
                "",
                "═" * 50,
                "  ⚠️ إدارات بدون بريد إلكتروني (تحتاج متابعة)",
                "═" * 50,
            ]
            for name, rows in no_email:
                body_lines.append(f"  • {name} — {rows} طلب")

        if new_dept:
            body_lines += [
                "",
                "═" * 50,
                "  🆕 إدارات جديدة تحتاج اعتماد",
                "═" * 50,
            ]
            for name, rows in new_dept:
                body_lines.append(f"  • {name} — {rows} طلب")

        if disabled:
            body_lines += [
                "",
                "═" * 50,
                "  🚫 إدارات معطّلة",
                "═" * 50,
            ]
            for name, rows in disabled:
                body_lines.append(f"  • {name} — {rows} طلب")

        if failed_list:
            body_lines += [
                "",
                "═" * 50,
                "  ❌ أخطاء",
                "═" * 50,
            ]
            for name, reason in failed_list:
                body_lines.append(f"  • {name}: {reason}")

        if summary.get("unassigned", 0) > 0:
            body_lines += [
                "",
                "═" * 50,
                "  📋 طلبات بدون إدارة محددة",
                "═" * 50,
                f"  عدد الطلبات: {summary['unassigned']}",
            ]

    if summary.get("failure_reason"):
        body_lines += [
            "",
            "═" * 50,
            "  ❌ خطأ في التشغيل",
            "═" * 50,
            f"  المرحلة: {summary.get('failure_stage', '')}",
            f"  السبب: {summary['failure_reason']}",
        ]

    body_lines += [
        "",
        "═" * 50,
        "",
        "وتفضلوا بقبول خالص التحية والتقدير.",
    ]

    body = "\n".join(body_lines)
    subject = f"تقرير الملاحظات والأخطاء — {today}"
    if test_to:
        subject = f"[تجربة] {subject}"

    if dry_run:
        print(f"  [جاهز ملخص] -> {to}")
        print(body)
        return True

    if not sender or not password:
        print("لم يتم تعيين بيانات الإرسال — تعذر إرسال الملخص.")
        return False

    try:
        server = _connect(sender, password)
        msg = _build_message(sender, to, "", subject, body, "")
        server.sendmail(sender, [to], msg.as_string())
        server.quit()
        print(f"  [أُرسل ملخص] -> {to}")
        return True
    except Exception as e:
        print(f"  [فشل ملخص] -> {to}: {e}")
        return False

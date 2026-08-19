# -*- coding: utf-8 -*-
"""
أمر test-send: إرسال/معاينة تجريبية للدورة اليومية على بيانات عينة واقعية.
- يولّد ملف تقرير تجريبي (بإدارات حقيقية من جدول الإعدادات + حالات ومناطق متنوعة).
- يمر على نفس دورة النظام: فحص ← فلاتر (الحالة + الغرب) ← تقسيم ← معاينة الرسائل.
- مع --eml يحفظ نسخ .eml من كل رسالة في output/معاينة_الإيميلات/ لفتحها في Outlook.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config_loader import BASE_DIR, env, load_config
from .export_excel import save_dataframes
from .send_email import _build_message
from .split_by_dept import apply_filters, split_by_department
from .validate_report import validate_report

COLUMNS = [
    "رقم الطلب", "نوع الطلب", "الخدمة الرئيسية", "الخدمة الفرعية", "المنشأ",
    "الحي", "مالك الطلب", "الفريق المالك للطلب", "الحالة", "تاريخ الإنشاء",
    "تاريخ التعديل", "المرحلة النشطة", "نوع مالك الطلب الحالي", "عدد التعليقات",
    "عدد مرات إعادة فتح الطلب", "حالة الطلب", "الإدارة - الوكالة الأساسية للطلب",
]

# بيانات عينة: إدارات غربية حقيقية من جدول الإعدادات + حالات ومناطق أخرى للاختبار
SAMPLE_ROWS = [
    # (رقم الطلب, الفريق المالك للطلب, حالة الطلب, الإدارة - الوكالة الأساسية للطلب)
    ("REQ-1001", "إدارة رخص البناء - غرب", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1002", "إدارة رخص البناء - غرب", "جاري العمل", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1003", "ادارة الرخص التجارية والاستثمارية - غرب", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1004", "إدارة الاستثمار - غرب", "جاري العمل", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1005", "إدارة الرقابة العمرانية - غرب", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1006", "إدارة رخص البناء - غرب", "منتهي", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1007", "إدارة رخص البناء - جنوب", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - جنوب"),
    ("REQ-1008", "إدارة رخص البناء - وسط", "جاري العمل", "الإدارة العامة لتنمية المدينة - وسط"),
    ("REQ-1009", "إدارة رخص البناء - شرق", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - شرق"),
    ("REQ-1010", "إدارة رخص البناء - شمال", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - شمال"),
    ("REQ-1011", "الإدارة العامة لتنمية المدينة - غرب", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - غرب"),
    ("REQ-1012", "", "قيد الإجراء", "الإدارة العامة لتنمية المدينة - غرب"),
]


def _build_sample_report() -> Path:
    cfg = load_config()
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = BASE_DIR / cfg["report"].get("download_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"تقرير_تجريبي_{today}.xlsx"

    rows = []
    for req_id, dept, status, region in SAMPLE_ROWS:
        rows.append({
            "رقم الطلب": req_id,
            "نوع الطلب": "طلب خدمة",
            "الخدمة الرئيسية": "خدمة البناء",
            "الخدمة الفرعية": "إصدار رخصة",
            "المنشأ": "منصة الخدمات",
            "الحي": "حي العليا",
            "مالك الطلب": "مستفيد",
            "الفريق المالك للطلب": dept,
            "الحالة": "نشط",
            "تاريخ الإنشاء": today,
            "تاريخ التعديل": today,
            "المرحلة النشطة": "المعالجة",
            "نوع مالك الطلب الحالي": "إدارة",
            "عدد التعليقات": "0",
            "عدد مرات إعادة فتح الطلب": "0",
            "حالة الطلب": status,
            "الإدارة - الوكالة الأساسية للطلب": region,
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_excel(path, index=False)
    print(f"✅ ملف تجريبي أُنشئ: {path} ({len(df)} سجل)")
    return path


def _safe_name(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip()[:60]


def run(eml: bool = False) -> int:
    cfg = load_config()
    email_cfg = cfg["email"]
    sender = env("SMTP_SENDER") or email_cfg.get("sender", "") or "test@example.com"

    # 1) توليد ملف العينة
    sample = _build_sample_report()

    # 2) فحص التقرير
    print("\n[1] فحص التقرير:")
    validation = validate_report(str(sample))
    if validation.get("decision") == "fail":
        print(f"    🔴 فشل الفحص: {validation.get('reason')}")
        return 1
    print(f"    ✅ {validation['rows']} سجل × {validation['cols']} عمود — {validation['reason']}")

    # 3) الفلاتر (الحالة + الغرب)
    print("\n[2] الفلاتر:")
    raw = pd.read_excel(sample)
    filtered = apply_filters(raw)
    print(f"    الناتج النهائي بعد الفلترة: {len(filtered)} سجل")

    # 4) التقسيم حسب الإدارة
    print("\n[3] التقسيم حسب الإدارة:")
    result = split_by_department(str(sample))
    if not result:
        print("    🔴 لم يتم إنشاء أي ملف إدارة")
        return 1
    print(f"    ✅ تم إنشاء {len(result)} ملف إدارة")

    # 5) تجهيز الرسائل (نفس منطق الإرسال الفعلي)
    print("\n[4] معاينة الرسائل:")
    today = datetime.now().strftime("%d-%m-%Y")
    global_cc = email_cfg.get("global_cc", "")
    ready, blocked = [], []
    for dept, info in result.items():
        action = info.get("action", "send")
        to = info.get("email", "")
        if action in ("new_dept", "no_email", "disabled") or not to:
            blocked.append((dept, info.get("reason", ""), action))
            continue
        dept_cc = info.get("cc", "")
        merged_cc = ",".join(filter(None, [global_cc, dept_cc]))
        ready.append({
            "dept": dept,
            "to": to,
            "cc": merged_cc,
            "subject": email_cfg["subject_template"].format(date=today),
            "body": email_cfg["body_template"].format(date=today, count=info.get("rows", 0), dept_name=dept),
            "attachment": info.get("file", ""),
            "rows": info.get("rows", 0),
        })

    eml_dir = None
    if eml:
        eml_dir = BASE_DIR / "output" / "معاينة_الإيميلات"
        eml_dir.mkdir(parents=True, exist_ok=True)

    for e in ready:
        print(f"  📧 {e['dept']} ({e['rows']} سجل)")
        print(f"     إلى: {e['to']}")
        if e["cc"]:
            print(f"     CC: {e['cc']}")
        print(f"     الموضوع: {e['subject']}")
        print(f"     المرفق: {Path(e['attachment']).name}")
        if eml_dir:
            msg = _build_message(sender, e["to"], e["cc"], e["subject"], e["body"], e["attachment"])
            eml_path = eml_dir / f"{_safe_name(e['dept'])}.eml"
            eml_path.write_text(msg.as_string(), encoding="utf-8")
            print(f"     💾 معاينة محفوظة: {eml_path.name}")

    if blocked:
        print("\n  ⛔ رسائل لن تُرسل:")
        for dept, reason, action in blocked:
            print(f"     - {dept}: {reason}")

    if not ready:
        print("\n🔴 لا توجد رسائل جاهزة للإرسال (كلها محظورة).")
        return 1

    print("\n" + "=" * 55)
    print(f"🧪 العينة الجاهزة للإرسال: {len(ready)} رسالة من أصل {len(result)} إدارة")
    if eml_dir:
        print(f"   ملفات المعاينة في: output/معاينة_الإيميلات/")
    print("=" * 55)
    print("\nلإرسال تجريبي حقيقي على جهازك (يتطلب ملف .env):")
    print(f"   python main.py run_daily --source {sample.name} --test-to بريدك@... ")
    return 0


if __name__ == "__main__":
    sys.exit(run(eml="--eml" in sys.argv))

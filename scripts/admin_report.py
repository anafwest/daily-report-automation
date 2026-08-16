from datetime import datetime

import pandas as pd

from .config_loader import BASE_DIR, load_config
from .export_excel import save_dataframes


def build_admin_report(run_id: str, summary: dict, result: dict = None,
                       failures: list = None, validation: dict = None) -> tuple:
    cfg = load_config()
    out = BASE_DIR / cfg["output"]["admin_report_file"]
    out.parent.mkdir(parents=True, exist_ok=True)

    status = summary.get("status", "fail")
    failures = failures or []
    result = result or {}
    validation = validation or {}

    header_rows = pd.DataFrame({
        "البند": ["Run ID", "التاريخ", "وقت البدء", "وقت الانتهاء", "الحالة"],
        "القيمة": [
            run_id,
            summary.get("date", datetime.now().strftime("%Y-%m-%d")),
            summary.get("start_time", ""),
            summary.get("end_time", ""),
            status,
        ],
    })

    counts_rows = pd.DataFrame({
        "المؤشر": [
            "إجمالي الطلبات", "الإدارات", "الملفات المنشأة",
            "الرسائل المرسلة", "الرسائل الفاشلة", "الطلبات غير المصنفة",
            "إدارات جديدة تحتاج اعتماد", "إدارات بلا بريد",
        ],
        "العدد": [
            summary.get("total_requests", 0),
            summary.get("total_depts", 0),
            summary.get("files_created", 0),
            summary.get("emails_sent", 0),
            summary.get("emails_failed", 0),
            summary.get("unassigned", 0),
            summary.get("new_depts", 0),
            summary.get("no_email", 0),
        ],
    })

    sheets = [("الملخص", header_rows), ("المؤشرات", counts_rows)]

    if result:
        rows = []
        for dept, info in result.items():
            rows.append({
                "الإدارة": dept,
                "عدد الطلبات": info.get("rows", 0),
                "البريد": info.get("email", ""),
                "الإجراء": info.get("action", ""),
                "السبب": info.get("reason", ""),
            })
        dept_frame = pd.DataFrame(rows)
        sheets.append(("الإدارات", dept_frame))

    if failures:
        f_rows = []
        for f in failures:
            dept, reason = (f, "") if isinstance(f, str) else f
            f_rows.append({"الإدارة": dept, "السبب": reason})
        sheets.append(("المراد متابعتها", pd.DataFrame(f_rows)))

    if validation:
        v_rows = pd.DataFrame({"الفحص": list(validation.keys()), "النتيجة": [str(v) for v in validation.values()]})
        sheets.append(("فحص التقرير", v_rows))

    save_dataframes(sheets, str(out))
    return str(out)

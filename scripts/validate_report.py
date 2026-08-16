from datetime import datetime
from pathlib import Path

import pandas as pd

from .config_loader import BASE_DIR, load_config


class ReportValidationError(Exception):
    pass


def _fmt_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def validate_report(file_path: str, sheet_name: int = 0) -> dict:
    cfg = load_config()
    rcfg = cfg["report"]
    path = Path(file_path)
    checks = {}

    checks["exists"] = path.exists()
    if not checks["exists"]:
        checks["decision"] = "fail"
        checks["reason"] = f"لم يتم العثور على ملف التقرير: {path}"
        return checks

    checks["extension"] = path.suffix.lower() in (".xlsx", ".xls")
    if not checks["extension"]:
        checks["decision"] = "fail"
        checks["reason"] = f"امتداد الملف غير مدعوم: {path.suffix}"
        return checks

    checks["today_marker"] = _fmt_date() in path.name
    if not checks["today_marker"]:
        checks["warnings"] = checks.get("warnings", []) + [
            f"اسم الملف لا يحتوي على تاريخ اليوم ({_fmt_date()}) — تأكد أنه تقرير اليوم."
        ]

    try:
        df = pd.read_excel(str(path), sheet_name=sheet_name)
    except Exception as e:
        checks["decision"] = "fail"
        checks["reason"] = f"تعذر قراءة الملف كـ Excel: {e}"
        return checks

    checks["readable"] = True
    checks["rows"] = int(len(df))
    checks["cols"] = int(df.shape[1])

    if checks["rows"] == 0:
        checks["decision"] = "fail"
        checks["reason"] = "التقرير فارغ (0 سجل)."
        return checks

    actual_cols = [str(c).strip() for c in df.columns]
    expected = [c for c in rcfg.get("expected_columns", [])]
    missing_expected = [c for c in expected if c not in actual_cols]
    checks["missing_expected"] = missing_expected
    if missing_expected:
        checks["warnings"] = checks.get("warnings", []) + [
            f"أعمدة متوقعة غير موجودة: {missing_expected} — راجع بنية التقرير."
        ]

    required = [rcfg["request_id_column"], rcfg["department_column"]]
    missing_required = [c for c in required if c not in actual_cols]
    checks["missing_required"] = missing_required
    if missing_required:
        checks["decision"] = "fail"
        checks["reason"] = f"أعمدة أساسية غير موجودة: {missing_required}"
        return checks

    req_series = df[rcfg["request_id_column"]]
    checks["request_ids_empty"] = int(req_series.isna().sum())
    if checks["request_ids_empty"] == checks["rows"]:
        checks["decision"] = "fail"
        checks["reason"] = "عمود رقم الطلب فارغ بالكامل."
        return checks

    max_records = int(rcfg.get("max_records", 100000))
    if checks["rows"] >= max_records:
        checks["decision"] = "warning"
        checks["reason"] = (
            f"عدد السجلات ({checks['rows']:,}) بلغ أو قارب حد البوابة ({max_records:,}). "
            "قد يكون التقرير مقصوصاً (جزء من البيانات فقط) — لا يُعتمد الإرسال قبل التأكد."
        )
        return checks

    checks["decision"] = "pass"
    checks["reason"] = "التقرير سليم."
    return checks


def load_report(file_path: str, sheet_name: int = 0):
    validation = validate_report(file_path, sheet_name)
    if validation.get("decision") == "fail":
        raise ReportValidationError(validation.get("reason", "فشل التحقق من التقرير"))
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    return df, validation

import pandas as pd

from .dept_settings import DeptSettings, load_dept_settings
from .export_excel import save_dataframes
from .normalize import normalize_dept_name
from .config_loader import BASE_DIR, load_config


def summarize(df: pd.DataFrame, dept_col: str = None, settings: DeptSettings = None) -> pd.DataFrame:
    cfg = load_config()
    rcfg = cfg["report"]
    dept_col = dept_col or rcfg["department_column"]
    settings = settings or load_dept_settings()

    if dept_col not in df.columns:
        raise ValueError(f"عمود الإدارة '{dept_col}' غير موجود.")

    df = df.copy()
    df["_dept_norm"] = df[dept_col].apply(
        lambda v: normalize_dept_name(v) if pd.notna(v) and str(v).strip() else ""
    )

    summary_rows = []
    for norm_name, group in df.groupby("_dept_norm"):
        entry = settings.find(norm_name) if norm_name else None
        summary_rows.append({
            "الإدارة": norm_name if norm_name else "غير مصنف",
            "البريد": entry["email"] if entry else "",
            "حالة الإرسال": entry["status"] if entry else "",
            "عدد الطلبات": len(group),
        })
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values("عدد الطلبات", ascending=False).reset_index(drop=True)
    return summary


def save_summary(df: pd.DataFrame):
    cfg = load_config()
    out = BASE_DIR / cfg["output"]["dept_summary_file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    save_dataframes([("ملخص الإدارات", df)], str(out))
    return str(out)

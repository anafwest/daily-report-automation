from pathlib import Path

import pandas as pd

from .config_loader import BASE_DIR, env, load_config
from .normalize import normalize_dept_name, normalize_key


def _s(v):
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return str(v).strip()


class DeptSettings:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.by_key = {}
        self.entries = []
        for _, row in df.iterrows():
            raw_name = _s(row.get("_dept_raw"))
            norm = normalize_dept_name(raw_name)
            key = normalize_key(norm)
            entry = {
                "raw_name": raw_name,
                "name": norm,
                "email": _s(row.get("email")),
                "cc": _s(row.get("cc")),
                "status": _s(row.get("status")) or "فعال",
                "row": row.to_dict(),
            }
            self.entries.append(entry)
            if key:
                self.by_key[key] = entry

    def find(self, raw_name: str):
        key = normalize_key(normalize_dept_name(raw_name))
        if not key:
            return None
        return self.by_key.get(key)

    def is_active(self, entry) -> bool:
        cfg = load_config()
        active = cfg["email_list"].get("active_values", ["فعال", "نشط", "مفعّل", "1"])
        return str(entry["status"]).strip() in active

    @property
    def count(self) -> int:
        return len(self.entries)


def load_dept_settings() -> DeptSettings:
    cfg = load_config()
    ecfg = cfg["email_list"]
    override = env("DEPT_SETTINGS_FILE")
    path = Path(override) if override else BASE_DIR / ecfg["file"]
    if not path.exists():
        print(f"ملف إعدادات الإدارات غير موجود: {path}")
        return DeptSettings(pd.DataFrame(columns=["الإدارة", "البريد الإلكتروني"]))

    df = pd.read_excel(path, dtype=str)
    dept_col = ecfg["dept_col"]
    if dept_col not in df.columns:
        print(f"عمود الإدارة '{dept_col}' غير موجود في {path}. الأعمدة: {list(df.columns)}")
        return DeptSettings(pd.DataFrame(columns=["الإدارة", "البريد الإلكتروني"]))

    df = df.rename(columns={
        dept_col: "_dept_raw",
        ecfg["email_col"]: "email",
        ecfg.get("cc_col", "CC"): "cc",
        ecfg.get("status_col", "حالة الإرسال"): "status",
    })
    for col in ["email", "cc", "status"]:
        if col not in df.columns:
            df[col] = ""
    df["_dept_raw"] = df["_dept_raw"].fillna("").astype(str).str.strip()
    df = df[df["_dept_raw"] != ""]
    return DeptSettings(df)

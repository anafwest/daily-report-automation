from pathlib import Path

import pandas as pd

from .config_loader import BASE_DIR, load_config
from .dept_settings import DeptSettings, load_dept_settings
from .export_excel import save_dataframes
from .normalize import normalize_dept_name


def _safe_file_name(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip()[:80]


def _find_column(columns, primary: str, aliases=()) -> str | None:
    """يبحث عن العمود المطلوب بالاسم الأساسي ثم بالأسماء البديلة (يتجاهل المسافات الزائدة)."""
    cols = [str(c).strip() for c in columns]
    if primary and primary in cols:
        return primary
    for alias in aliases or []:
        if alias and alias in cols:
            return alias
    return None


def apply_filters(raw) -> pd.DataFrame:
    """يطبّق فلتر الحالة (قيد الإجراء/جاري العمل) ثم فلتر المنطقة (الغرب فقط) على التقرير الخام."""
    cfg = load_config()
    rcfg = cfg["report"]
    raw = raw.copy()

    # 1) فلتر حالة الطلب
    status_col = _find_column(
        raw.columns,
        rcfg.get("status_column", ""),
        rcfg.get("status_column_aliases", []),
    )
    allowed = rcfg.get("allowed_statuses", [])
    if status_col and allowed:
        before = len(raw)
        mask = raw[status_col].astype(str).str.strip().isin(allowed)
        raw = raw[mask].reset_index(drop=True)
        print(f"فلتر الحالة ({status_col}): {before:,} → {len(raw):,} سجل (المسموح: {allowed})")
    elif rcfg.get("status_column"):
        print(f"تحذير: عمود الحالة '{rcfg['status_column']}' غير موجود في التقرير — تم تخطي فلتر الحالة.")

    # 2) فلتر المنطقة (الغرب فقط)
    rfilter = rcfg.get("region_filter", {})
    if rfilter.get("enabled"):
        reg_col = _find_column(
            raw.columns,
            rfilter.get("column", ""),
            rfilter.get("fallback_columns", []),
        )
        keywords = [str(k).strip() for k in rfilter.get("keywords", []) if str(k).strip()]
        if reg_col and keywords:
            before = len(raw)
            mask = raw[reg_col].astype(str).apply(
                lambda v: any(k in v for k in keywords)
            )
            raw = raw[mask].reset_index(drop=True)
            print(f"فلتر المنطقة ({reg_col}): {before:,} → {len(raw):,} سجل (يُحتفظ فقط بـ: {keywords})")
        elif not reg_col:
            print(f"تحذير: عمود المنطقة '{rfilter.get('column')}' غير موجود في التقرير — تم تخطي فلتر المنطقة.")

    return raw


def split_by_department(source_file: str, sheet_name: int = 0,
                        settings: DeptSettings = None) -> dict:
    cfg = load_config()
    rcfg = cfg["report"]
    dept_col = rcfg["department_column"]
    settings = settings or load_dept_settings()

    raw = pd.read_excel(source_file, sheet_name=sheet_name)

    # تطبيق فلتر الحالة (قيد الإجراء/جاري العمل) + فلتر المنطقة (الغرب فقط)
    raw = apply_filters(raw)

    if dept_col not in raw.columns:
        print(f"عمود '{dept_col}' غير موجود. الأعمدة المتاحة: {list(raw.columns)}")
        return {}

    out_dir = BASE_DIR / cfg["output"]["split_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = raw.copy()
    raw["_dept_raw"] = raw[dept_col].apply(
        lambda v: str(v).strip() if pd.notna(v) else ""
    )
    raw["_dept_norm"] = raw["_dept_raw"].apply(normalize_dept_name)

    result = {}
    unassigned = []
    new_depts = []
    no_email = []

    for norm_name, group in raw.groupby("_dept_norm"):
        display = norm_name or "غير مصنف"
        if not norm_name:
            unassigned.append(group)
            continue

        entry = settings.find(norm_name)
        if entry is None:
            new_depts.append(norm_name)
            file_name = _safe_file_name(display)
            path = out_dir / f"{file_name}.xlsx"
            save_dataframes([(display, group.reset_index(drop=True))], str(path))
            result[display] = {
                "file": str(path), "rows": len(group),
                "email": "", "cc": "", "status": "",
                "action": "new_dept",
                "reason": "إدارة جديدة تحتاج اعتماد التوزيع",
            }
            continue

        if not entry["email"]:
            no_email.append(display)
            file_name = _safe_file_name(display)
            path = out_dir / f"{file_name}.xlsx"
            save_dataframes([(display, group.reset_index(drop=True))], str(path))
            result[display] = {
                "file": str(path), "rows": len(group),
                "email": "", "cc": entry["cc"], "status": entry["status"],
                "action": "no_email",
                "reason": "لا يوجد بريد معتمد في جدول الإعدادات",
            }
            continue

        file_name = _safe_file_name(display)
        path = out_dir / f"{file_name}.xlsx"
        save_dataframes([(display, group.reset_index(drop=True))], str(path))
        result[display] = {
            "file": str(path), "rows": len(group),
            "email": entry["email"], "cc": entry["cc"], "status": entry["status"],
            "action": "send" if settings.is_active(entry) else "disabled",
            "reason": "" if settings.is_active(entry) else "حالة الإرسال معطّلة في الإعدادات",
        }

    def _save_list(name, frame, out_path, sheet_name):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        save_dataframes([(sheet_name, frame)], str(out_path))

    if unassigned:
        frame = pd.concat(unassigned, ignore_index=True)
        _save_list("غير مصنف", frame, BASE_DIR / cfg["output"]["unassigned_file"], "غير مصنف")
        print(f"طلبات بدون إدارة ({len(frame)}): حفظت في {cfg['output']['unassigned_file']}")

    if no_email:
        frame = pd.DataFrame({"الإدارة": no_email})
        _save_list("بدون بريد", frame, BASE_DIR / cfg["output"]["no_email_file"], "بدون بريد")
        print(f"إدارات بلا بريد ({len(no_email)}): {', '.join(no_email)}")

    if new_depts:
        frame = pd.DataFrame({"الإدارة": new_depts})
        _save_list("جديدة", frame, BASE_DIR / cfg["output"]["new_dept_file"], "جديدة")
        print(f"إدارات جديدة تحتاج اعتماد ({len(new_depts)}): {', '.join(new_depts)}")

    return result

import re
import unicodedata

from .config_loader import load_config

_SPACE_CHARS = ["\u00a0", "\u200f", "\u200e", "\u202f", "\u200b", "\ufeff", " "]
_DASH_CHARS = ["-", "–", "—", "−", "ـ", "_"]
_BRACKETS = {"(", ")", "[", "]", "{", "}", "（", "）"}


def _clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _clean_dashes(s: str) -> str:
    return re.sub(r"\s*[–—−_ـ]\s*", " - ", s).strip()


def _clean_brackets(s: str) -> str:
    return re.sub(r"[\(\)\[\]\{\}（）]", " ", s).strip()


def normalize_dept_name(name) -> str:
    cfg = load_config()
    norm_cfg = cfg.get("matching", {}).get("normalize", {})
    if name is None:
        return ""
    s = str(name)
    s = unicodedata.normalize("NFC", s)
    for ch in _SPACE_CHARS:
        s = s.replace(ch, " ")
    if norm_cfg.get("strip_dashes", True):
        s = _clean_dashes(s)
    if norm_cfg.get("strip_brackets", True):
        s = _clean_brackets(s)
    s = re.sub(r"\s+", " ", s).strip()
    if norm_cfg.get("strip_spaces", True):
        s = " ".join(s.split())
    replacements = norm_cfg.get("replacements", {})
    for old, new in replacements.items():
        s = s.replace(old, new)
    if norm_cfg.get("unify_admin_term", True):
        admin_term = norm_cfg.get("admin_term", "إدارة")
        if admin_term and not s.startswith(admin_term):
            pass
    return s


def normalize_key(name) -> str:
    s = normalize_dept_name(name)
    return re.sub(r"[^0-9\u0600-\u06FFa-zA-Z]", "", s).lower()


def matches(normalized_name: str, settings_name: str) -> bool:
    return normalize_key(normalized_name) == normalize_key(settings_name)

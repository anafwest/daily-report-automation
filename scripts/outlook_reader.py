import re
import time

OTP_KEYWORDS = [
    "رمز التحقق",
    "رمز الدخول",
    "رمز تحقق",
    "كلمة المرور",
    "الكود",
    "otp",
    "verification",
]

OUTLOOK_CLIENT = None


def _client():
    global OUTLOOK_CLIENT
    if OUTLOOK_CLIENT is None:
        import win32com.client

        OUTLOOK_CLIENT = win32com.client.Dispatch("Outlook.Application")
    return OUTLOOK_CLIENT


def outlook_available() -> bool:
    try:
        _client().GetNamespace("MAPI")
        return True
    except Exception:
        return False


def _iter_recent(max_items=10):
    ns = _client().GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    for i in range(min(max_items, items.Count)):
        try:
            m = items.Item(i + 1)
            yield m, (m.Subject or ""), (m.Body or "")
        except Exception:
            continue


def _is_otp(subj: str, body: str) -> bool:
    text = f"{subj} {body}".lower()
    return any(kw.lower() in text for kw in OTP_KEYWORDS)


def _extract_code(text: str):
    m = re.findall(r"(?<!\d)\d{4,6}(?!\d)", text or "")
    return m[0] if m else None


def snapshot_codes(since_minutes=60, max_items=10):
    codes = set()
    for m, subj, body in _iter_recent(max_items):
        if not _is_otp(subj, body):
            continue
        c = _extract_code(body)
        if c:
            codes.add(c)
    return codes


def read_latest_otp(max_items=8):
    for m, subj, body in _iter_recent(max_items):
        if not _is_otp(subj, body):
            continue
        c = _extract_code(body)
        if c:
            return c
    return ""


def wait_new_code(known_codes: set, timeout_sec=90, poll_sec=2.0):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            for m, subj, body in _iter_recent(5):
                if not _is_otp(subj, body):
                    continue
                c = _extract_code(body)
                if c and c not in known_codes:
                    print(f"  رمز التحقق الجديد وصل في Outlook: {c}")
                    return c
        except Exception as e:
            print(f"  خطأ أثناء فحص Outlook: {e}")
        time.sleep(poll_sec)
    return ""

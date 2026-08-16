import imaplib
import re
import time
from email import policy
from email.header import decode_header
from email.message import Message


def _decode(value) -> str:
    if not value:
        return ""
    out = ""
    for data, enc in decode_header(value):
        if isinstance(data, bytes):
            out += data.decode(enc or "utf-8", errors="ignore")
        else:
            out += data
    return out


def _body_text(msg: Message) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_content()
                    except Exception:
                        pass
        else:
            return msg.get_content()
    except Exception:
        pass
    return ""


def _extract_code(subject: str, body: str):
    matches = re.findall(r"\b\d{4,6}\b", f"{subject}\n{body}")
    return matches[0] if matches else None


def _matches(subject: str, body: str, keywords) -> bool:
    hay = f"{subject}\n{body}"
    return any(kw in hay for kw in keywords)


def _fetch_new(m, after_uid: int, keywords, prefix=""):
    typ, data = m.uid("search", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return None
    uids = []
    for u in data[0].split():
        try:
            if int(u) > after_uid:
                uids.append(u)
        except Exception:
            pass
    for uid in uids:
        typ2, msg_data = m.uid("fetch", uid, "(RFC822)")
        if typ2 != "OK" or not msg_data or msg_data[0] is None:
            continue
        raw = msg_data[0][1]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        msg = __import__("email").message_from_string(raw, policy=policy.default)
        subject = _decode(msg.get("Subject", ""))
        body = _body_text(msg)
        if _matches(subject, body, keywords):
            code = _extract_code(subject, body)
            if code:
                print(f"{prefix}تم العثور على رمز التحقق في البريد (الموضوع: {subject[:60]})")
                return code
    return None


def get_last_uid(imap_server, imap_port, email_addr, password) -> int:
    m = imaplib.IMAP4_SSL(imap_server, imap_port)
    m.login(email_addr, password)
    m.select("INBOX")
    try:
        typ, data = m.uid("search", None, "ALL")
        if typ == "OK" and data and data[0]:
            uids = data[0].split()
            if uids:
                try:
                    return int(uids[-1])
                except Exception:
                    pass
        return 0
    finally:
        try:
            m.logout()
        except Exception:
            pass


def fetch_otp(imap_server, imap_port, email_addr, password, keywords, base_uid=0, timeout_sec=120) -> str:
    m = None
    try:
        m = imaplib.IMAP4_SSL(imap_server, imap_port)
        m.login(email_addr, password)
        m.select("INBOX")
    except Exception as e:
        print(f"  تعذر الاتصال بالبريد: {e}")
        return ""
    deadline = time.time() + timeout_sec
    try:
        while time.time() < deadline:
            code = _fetch_new(m, base_uid, keywords, prefix="  ")
            if code:
                return code
            time.sleep(4)
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return ""

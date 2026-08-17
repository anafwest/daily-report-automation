import time

from playwright.sync_api import sync_playwright

from .browser_session import open_persistent_context

MAILBOX_URL = "https://mail.alriyadh.gov.sa/owa/"

SEL_NEW = "button[aria-label='بريد جديد']"
SEL_TO = "div[aria-label='إلى']"
SEL_CC = "div[aria-label='نسخة']"
SEL_SUBJECT = "input[aria-label='الموضوع']"
SEL_BODY = "div[aria-label='النص الأساسي للرسالة']"
SEL_ATTACH = "button[aria-label='إرفاق ملف']"
SEL_SEND = [
    "button[aria-label='إرسال']",
    "button[title='إرسال']",
    "button[aria-label='إرسال (Ctrl+Enter)']",
]


def _click(page, selectors, timeout=10000):
    if isinstance(selectors, str):
        selectors = [selectors]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible():
                el.click(timeout=timeout)
                return True
        except Exception:
            pass
    return False


def _type_recipient(page, sel, value):
    el = page.locator(sel).first
    el.wait_for(state="visible", timeout=10000)
    el.click()
    page.wait_for_timeout(400)
    page.keyboard.type(value, delay=25)
    page.wait_for_timeout(900)
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)


def _type_body(page, text):
    el = page.locator(SEL_BODY).first
    el.wait_for(state="visible", timeout=10000)
    el.click()
    page.wait_for_timeout(300)
    for line in text.split("\n"):
        page.keyboard.type(line, delay=5)
        page.keyboard.press("Enter")


def _attach_file(page, path):
    from pathlib import Path as _Path

    fname = _Path(path).name
    img_input = page.locator("input[type='file'][accept='image/*']")
    general = page.locator("input[type='file']:not([accept='image/*'])")
    target = general.first if general.count() else img_input.first
    target.set_input_files(path)
    deadline = time.time() + 25
    while time.time() < deadline:
        if page.locator(f"text='{fname}'").count() > 0:
            break
        page.wait_for_timeout(1000)
    page.wait_for_timeout(2000)


def _compose_visible(page) -> bool:
    try:
        return page.locator(SEL_TO).count() > 0 and page.locator(SEL_TO).first.is_visible()
    except Exception:
        return False


def _send_one(page, item) -> bool:
    if not _click(page, SEL_NEW):
        return False
    page.wait_for_timeout(2500)
    if not _compose_visible(page):
        return False

    _type_recipient(page, SEL_TO, item.get("to", ""))
    cc = item.get("cc", "")
    if cc:
        _type_recipient(page, SEL_CC, cc)

    subject = item.get("subject", "")
    if subject:
        try:
            page.locator(SEL_SUBJECT).first.fill(subject)
        except Exception:
            page.locator(SEL_SUBJECT).first.click()
            page.keyboard.type(subject, delay=10)

    body = item.get("body", "")
    if body:
        _type_body(page, body)

    att = item.get("attachment", "")
    if att:
        _attach_file(page, att)

    if not _click(page, SEL_SEND):
        return False
    deadline = time.time() + 30
    while time.time() < deadline:
        if not _compose_visible(page):
            return True
        page.wait_for_timeout(1000)
    return False


def send_emails_via_owa(emails: list, dry_run: bool = False) -> tuple:
    sent, failed = [], []
    if dry_run:
        print("=" * 55)
        print(f"وضع تجربة OWA (بدون إرسال فعلي) - {len(emails)} رسالة")
        print("=" * 55)
        for e in emails:
            print(f"  [جاهز] -> {e.get('to')}" + (f" | CC: {e.get('cc')}" if e.get("cc") else ""))
            sent.append(e)
        return sent, failed

    with sync_playwright() as p:
        ctx, page = open_persistent_context(p, headless=False)
        try:
            page.goto(MAILBOX_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(7000)
            if not _click(page, SEL_NEW):
                print("  تعذر فتح نافذة إنشاء رسالة — جلسة البريد قد انتهت.")
                failed = list(emails)
                return [], failed
            page.wait_for_timeout(2000)
            if not _compose_visible(page):
                print("  تعذر فتح نافذة الإنشاء — تحقق من الدخول إلى صندوق البريد.")
                failed = list(emails)
                return [], failed
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(1500)
            for e in emails:
                try:
                    if _send_one(page, e):
                        print(f"  [أُرسل] -> {e.get('to')}")
                        sent.append(e)
                    else:
                        print(f"  [فشل] -> {e.get('to')}: لم يتأكد الإرسال")
                        _dump_state(page)
                        failed.append(e)
                except Exception as ex:
                    print(f"  [فشل] -> {e.get('to')}: {ex}")
                    failed.append(e)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return sent, failed


def _dump_state(page):
    try:
        print(f"    compose_vis={page.locator(SEL_TO).count() > 0 and page.locator(SEL_TO).first.is_visible()}")
    except Exception:
        pass
    try:
        print(f"    backdrop={page.locator('.fui-DialogSurface__backdrop').count()}")
    except Exception:
        pass
    try:
        txt = page.inner_text("body")[:250].replace("\n", " ▸ ")
        print(f"    body: {txt}")
    except Exception:
        pass

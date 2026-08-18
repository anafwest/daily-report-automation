import time

from playwright.sync_api import sync_playwright

from .browser_session import open_persistent_context

WHATSAPP_URL = "https://web.whatsapp.com/"
SAUDI_COUNTRY_CODE = "966"


def _format_number(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        phone = SAUDI_COUNTRY_CODE + phone[1:]
    if phone.startswith("+"):
        phone = phone[1:]
    return phone


def _wait_for_logged_in(page, timeout_sec=120):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if page.locator("[data-testid='chat-list']").count() > 0:
                return True
            if page.locator("[title='قائمة المحادثات']").count() > 0:
                return True
            if page.locator("[data-testid='default-user']").count() > 0:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def _send_message(page, phone: str, message: str, timeout_sec=60) -> bool:
    url = f"https://web.whatsapp.com/send?phone={phone}"
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(8)

    deadline = time.time() + timeout_sec
    msg_box = None
    while time.time() < deadline:
        try:
            msg_box = page.locator("[data-testid='conversation-compose-box-input']")
            if msg_box.count() > 0 and msg_box.first.is_visible():
                break
            msg_box = page.locator("[contenteditable='true'][data-tab='10']")
            if msg_box.count() > 0 and msg_box.first.is_visible():
                break
        except Exception:
            pass
        time.sleep(2)

    if msg_box is None or msg_box.count() == 0:
        return False

    try:
        msg_box.first.click()
        time.sleep(0.5)
        for line in message.split("\n"):
            page.keyboard.type(line, delay=8)
            page.keyboard.press("Shift+Enter")
        time.sleep(0.3)
        page.keyboard.press("Enter")
        time.sleep(3)

        err = page.locator("[data-testid='popup-controls-bar']")
        if err.count() > 0:
            try:
                page.locator("button:has-text('موافق'), button:has-text('OK')").first.click(timeout=3000)
            except Exception:
                pass
            return False
        return True
    except Exception:
        return False


def send_whatsapp_summary(summary_text: str, phone_numbers: list, dry_run: bool = False) -> tuple:
    sent, failed = [], []

    if dry_run:
        print("=" * 55)
        print(f"وضع تجربة واتساب (بدون إرسال فعلي) - {len(phone_numbers)} أرقام")
        print("=" * 55)
        for num in phone_numbers:
            print(f"  [جاهز] -> {num}")
            sent.append(num)
        return sent, failed

    if not phone_numbers:
        return sent, failed

    with sync_playwright() as p:
        ctx, page = open_persistent_context(p, headless=False)
        try:
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)

            if not _wait_for_logged_in(page, timeout_sec=120):
                print("  تعذر الدخول إلى واتساب. امسح رمز QR ثم أعد المحاولة.")
                failed = list(phone_numbers)
                return [], failed

            print("  تم الدخول إلى واتساب بنجاح.")
            time.sleep(3)

            for num in phone_numbers:
                formatted = _format_number(num)
                try:
                    if _send_message(page, formatted, summary_text):
                        print(f"  [أُرسل] -> {num}")
                        sent.append(num)
                    else:
                        print(f"  [فشل] -> {num}: لم يتأكد الإرسال")
                        failed.append(num)
                except Exception as ex:
                    print(f"  [فشل] -> {num}: {ex}")
                    failed.append(num)
                time.sleep(2)
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    return sent, failed


def build_summary_message(total_requests: int, total_depts: int, emails_sent: int,
                           emails_failed: int, unassigned: int, new_depts: int,
                           no_email: int, date: str = "") -> str:
    from datetime import datetime
    date = date or datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"تقرير يومي - {date}",
        "",
        f"إجمالي الطلبات: {total_requests:,}",
        f"الإدارات: {total_depts}",
        f"الرسائل المرسلة: {emails_sent}",
        f"الرسائل الفاشلة: {emails_failed}",
        f"طلبات بدون إدارة: {unassigned}",
        f"إدارات جديدة: {new_depts}",
        f"إدارات بلا بريد: {no_email}",
    ]
    return "\n".join(lines)

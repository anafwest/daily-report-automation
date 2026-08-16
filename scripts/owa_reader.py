import re
import time

from .browser_session import open_persistent_context

MSG_SELECTORS = [
    "[role='option']",
    "[role='listitem']",
    "[data-testid*='message']",
    "[role='treeitem']",
]


def _safe_all(page, selector, limit=40):
    try:
        return page.locator(selector).all()[:limit]
    except Exception:
        return []


def _page_dead(page) -> bool:
    try:
        return page.is_closed()
    except Exception:
        return True


def _fill_and_click(page, selector, value=None):
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=15000)
    if value is not None:
        el.fill(value)
    return el


def _ms_login(page, email_addr, password):
    page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    try:
        mo = page.locator("#moreOptions")
        if mo.count() and mo.is_visible():
            mo.click()
            page.wait_for_timeout(3000)
    except Exception:
        pass
    if not page.locator("#i0116").count():
        return False
    _fill_and_click(page, "#i0116", email_addr)
    page.locator("#idSIButton9").click()
    page.wait_for_timeout(4000)
    try:
        _fill_and_click(page, "#i0118", password)
        page.locator("#idSIButton9").click()
    except Exception:
        return False
    page.wait_for_timeout(6000)
    try:
        stay_yes = page.locator("#idSIButton9")
        if stay_yes.count() and stay_yes.is_visible():
            stay_yes.click()
            page.wait_for_timeout(6000)
    except Exception:
        pass
    return True


def _extract_code(text: str):
    matches = re.findall(r"(?<!\d)\d{4,6}(?!\d)", text)
    return matches[0] if matches else None


def _score(text: str) -> int:
    keywords = ["تحقق", "رمز", "الدخول", "رمز التحقق", "رمز الدخول", "verification", "otp", "كلمة المرور", "كود"]
    return sum(1 for kw in keywords if kw.lower() in text.lower())


def _scan_mail(page, keywords):
    seen = set()
    first_with_code = None
    for sel in MSG_SELECTORS:
        for item in _safe_all(page, sel, 30):
            try:
                if not item.is_visible():
                    continue
                txt = item.inner_text()
            except Exception:
                continue
            key = txt[:80]
            if key in seen:
                continue
            seen.add(key)
            code = _extract_code(txt)
            if not code:
                continue
            if first_with_code is None:
                first_with_code = (code, txt)
            if _score(txt) >= 1:
                print(f"  رمز التحقق الأحدث في البريد: {code} | {txt.replace(chr(10), ' ')[:70]}")
                return code
    if first_with_code:
        print(f"  رمز مكتشف في البريد: {first_with_code[0]} | {first_with_code[1].replace(chr(10), ' ')[:70]}")
        return first_with_code[0]
    return None


def _scan_all_codes(page) -> set:
    codes = set()
    seen = set()
    for sel in MSG_SELECTORS:
        for item in _safe_all(page, sel, 40):
            try:
                if not item.is_visible():
                    continue
                txt = item.inner_text()
            except Exception:
                continue
            key = txt[:80]
            if key in seen:
                continue
            seen.add(key)
            code = _extract_code(txt)
            if code and _score(txt) >= 1:
                codes.add(code)
    return codes


def _first_fresh(page, known_codes: set):
    seen = set()
    for sel in MSG_SELECTORS:
        for item in _safe_all(page, sel, 40):
            try:
                if not item.is_visible():
                    continue
                txt = item.inner_text()
            except Exception:
                continue
            key = txt[:80]
            if key in seen:
                continue
            seen.add(key)
            code = _extract_code(txt)
            if code and _score(txt) >= 1 and code not in known_codes:
                return code, txt.replace(chr(10), " ")[:70]
    return None


def snapshot_codes(page) -> set:
    try:
        return _scan_all_codes(page)
    except Exception:
        return set()


def open_mailbox_tab(page, email_addr, password, headless=False):
    tab = page.context.new_page()
    try:
        if _open_mailbox(tab, email_addr, password, headless):
            return tab
    except Exception as e:
        print(f"  تعذر فتح صندوق البريد: {e}")
    try:
        tab.close()
    except Exception:
        pass
    return None


def wait_new_code(tab, known_codes: set, timeout_sec=75, email_addr="", password="", headless=False):
    deadline = time.time() + timeout_sec
    reconnect_after = time.time() + 20
    reload_after = time.time() + 20
    while time.time() < deadline:
        if _page_dead(tab):
            try:
                if email_addr and _open_mailbox(tab, email_addr, password, headless):
                    reconnect_after = time.time() + 20
                    continue
            except Exception:
                pass
            print("  تبويب البريد أُغلق ولم يمكن إعادة فتحه.")
            return ""
        fresh = _first_fresh(tab, known_codes)
        if fresh:
            code, txt = fresh
            print(f"  رمز التحقق الجديد وصل: {code} | {txt}")
            return code
        if time.time() >= reload_after:
            try:
                tab.reload(wait_until="domcontentloaded")
            except Exception:
                pass
            reload_after = time.time() + 20
        else:
            try:
                tab.wait_for_timeout(3000)
            except Exception:
                pass
        if time.time() >= reconnect_after:
            if email_addr:
                try:
                    if _open_mailbox(tab, email_addr, password, headless):
                        print("  أُعيد فتح صندوق البريد (كان قد انتقل/أغلق).")
                        reconnect_after = time.time() + 20
                        continue
                except Exception as e:
                    print(f"  تعذر إعادة فتح صندوق البريد: {e}")
            return ""
    return ""


def _open_mailbox(page, email_addr, password, headless):
    page.goto("https://outlook.office.com/mail/", wait_until="domcontentloaded")
    deadline = time.time() + 60
    filled_login = False
    clicked_tile = False
    while time.time() < deadline:
        try:
            url = page.url
        except Exception:
            url = ""
        if "/mail/" in url and "login.microsoftonline.com" not in url:
            page.wait_for_timeout(4000)
            return True
        if not clicked_tile:
            for el in page.locator(".tile-container div, [role='option']").all():
                try:
                    if el.is_visible() and email_addr in (el.inner_text() or ""):
                        el.click()
                        clicked_tile = True
                        page.wait_for_timeout(5000)
                        break
                except Exception:
                    pass
        if page.locator("#i0116").count() and page.locator("#i0116").is_visible():
            if not filled_login:
                _fill_and_click(page, "#i0116", email_addr)
                page.locator("#idSIButton9").click()
                page.wait_for_timeout(4000)
                filled_login = True
                continue
            if page.locator("#i0118").count() and page.locator("#i0118").is_visible():
                _fill_and_click(page, "#i0118", password)
                page.locator("#idSIButton9").click()
                page.wait_for_timeout(6000)
                try:
                    stay = page.locator("#idBtn_Back")
                    if stay.count() and stay.is_visible():
                        stay.click()
                        page.wait_for_timeout(3000)
                except Exception:
                    pass
                filled_login = True
        try:
            mo = page.locator("#moreOptions")
            if mo.count() and mo.is_visible():
                mo.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass
        try:
            yes_btn = page.locator("input[type='submit'][value='نعم'], #idSIButton9")
            if yes_btn.count() and yes_btn.is_visible():
                print("  تأكيد الإبقاء على تسجيل الدخول (نعم)...")
                yes_btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
    return "/mail/" in page.url and "login.microsoftonline.com" not in page.url


def read_otp_owa(email_addr, password, timeout_sec=90, page=None, headless=False, known_codes=None, tab=None):
    deadline = time.time() + timeout_sec
    if page is not None:
        context = page.context
        close_tab = tab is None
        if tab is None:
            tab = context.new_page()
        try:
            if not _open_mailbox(tab, email_addr, password, headless):
                return ""
            while time.time() < deadline:
                if known_codes:
                    fresh = _first_fresh(tab, known_codes)
                    if fresh:
                        print(f"  رمز التحقق الجديد وصل: {fresh[0]} | {fresh[1]}")
                        return fresh[0]
                else:
                    code = _scan_mail(tab, [])
                    if code:
                        return code
                tab.wait_for_timeout(6000)
                try:
                    tab.reload(wait_until="domcontentloaded")
                    tab.wait_for_timeout(7000)
                except Exception:
                    pass
        finally:
            if close_tab:
                try:
                    tab.close()
                except Exception:
                    pass
        return ""

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context, page = open_persistent_context(p, headless)
        try:
            if not _open_mailbox(page, email_addr, password, headless):
                return ""
            while time.time() < deadline:
                if known_codes:
                    fresh = _first_fresh(page, known_codes)
                    if fresh:
                        print(f"  رمز التحقق الجديد وصل: {fresh[0]} | {fresh[1]}")
                        return fresh[0]
                else:
                    code = _scan_mail(page, [])
                    if code:
                        return code
                page.wait_for_timeout(6000)
                try:
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(7000)
                except Exception:
                    pass
        finally:
            context.close()
    return ""

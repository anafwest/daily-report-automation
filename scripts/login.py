import sys
import time

from playwright.sync_api import sync_playwright

from .browser_session import EDGE_PROFILE, open_persistent_context
from .config_loader import BASE_DIR, env, load_config
from .imap_reader import fetch_otp, get_last_uid
from .owa_reader import read_otp_owa

PROFILE_DIR = BASE_DIR / ".browser_profile"

CAPTCHA_IMG = "#pt1\\:i1"
CAPTCHA_INPUT = "#pt1\\:it3"
CAPTCHA_REFRESH = "#pt1\\:l1"
OTP_BOXES = ["#first", "#second", "#third", "#fourth"]
LOGIN_PATH = "https://app.alriyadh.gov.sa/SSO/faces/login"

_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        import ddddocr

        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


def _has_session() -> bool:
    return (PROFILE_DIR / "chrome_profile").exists() or PROFILE_DIR.exists()


def is_logged_in(page, home_path="/SSO/faces/home", timeout_sec=30) -> bool:
    try:
        page.goto(f"https://app.alriyadh.gov.sa{home_path}", wait_until="domcontentloaded")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            url = _strip_url(page.url)
            if "/faces/home" in url or "/faces/login" in url:
                return "/faces/home" in url
            if page.locator("#pt1\\:unameInputId").count() > 0:
                return False
        return False
    except Exception:
        return False


def ensure_logged_in(page, cfg) -> bool:
    if is_logged_in(page):
        print("الجلسة سليمة — لا حاجة لإعادة الدخول.")
        return True
    print("لا توجد جلسة صالحة — تنفيذ الدخول التلقائي...")
    return _auto_login(page, cfg)


def _build_context(playwright, headless: bool):
    return open_persistent_context(playwright, headless)


def save_session(context):
    PROFILE_DIR.mkdir(exist_ok=True)
    try:
        context.storage_state(path=str(PROFILE_DIR / "session.json"))
    except Exception:
        pass


def _print_inputs(page):
    print("=" * 60)
    print("حقول النموذج المكتشفة على صفحة الدخول:")
    for el in page.locator("input, button, a[role='button']").all():
        try:
            tag = el.evaluate("e => e.tagName")
            name = el.get_attribute("name") or ""
            el_id = el.get_attribute("id") or ""
            itype = el.get_attribute("type") or ""
            placeholder = el.get_attribute("placeholder") or ""
            text = el.inner_text()[:40] if tag in ("BUTTON", "A") else ""
            print(f"  {tag}  type={itype}  name={name}  id={el_id}  placeholder={placeholder}  text={text}")
        except Exception:
            pass
    print("=" * 60)


def _captcha_visible(page) -> bool:
    try:
        return page.locator("#divKaptchaId").is_visible()
    except Exception:
        return False


def _type_into(page, selector: str, value: str):
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=15000)
    el.click()
    page.wait_for_timeout(300)
    el.press_sequentially(value, delay=30)


def _solve_captcha(page) -> bool:
    img = page.locator(CAPTCHA_IMG)
    try:
        img.wait_for(state="visible", timeout=8000)
    except Exception:
        return False
    shot = PROFILE_DIR / "captcha_tmp.png"
    shot.parent.mkdir(exist_ok=True)
    img.screenshot(path=str(shot))
    with open(shot, "rb") as f:
        data = f.read()
    text = _get_ocr().classification(data)
    if not text:
        return False
    page.locator(CAPTCHA_INPUT).fill(text)
    print(f"  كابتشا مكتشفة: {text}")
    return True


def _wait_for_otp_panel(page, timeout_sec: int = 30) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if page.locator(OTP_BOXES[0]).is_visible():
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _fill_otp(page, code: str):
    digits = code[:4]
    for box_id, ch in zip(OTP_BOXES, digits):
        box = page.locator(box_id)
        box.click()
        page.wait_for_timeout(120)
        box.press(ch)
        page.wait_for_timeout(120)

    def _box_values():
        vals = []
        for box_id in OTP_BOXES:
            try:
                vals.append(page.locator(box_id).input_value() or "")
            except Exception:
                vals.append("")
        return "".join(vals)

    filled = _box_values()
    if filled != digits:
        print(f"  ملاحظة: قيم الخانات بعد الكتابة = '{filled}' — محاولة التعبئة المباشرة.")
        for box_id, ch in zip(OTP_BOXES, digits):
            try:
                page.locator(box_id).fill(ch)
                page.wait_for_timeout(80)
            except Exception:
                pass
        filled = _box_values()
    print(f"  تم تعبئة رمز التحقق تلقائياً (قيم الخانات: {filled}).")
    page.wait_for_timeout(300)
    clicked = False
    for sel in [
        "button:has-text('تحقق')",
        "[role='button']:has-text('تحقق')",
        "a:has-text('تحقق')",
        "button:has-text('تسجيل دخول')",
        "#clickVerifyId",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(force=True, timeout=5000)
                clicked = True
                print("  تم النقر على زر التحقق للدخول.")
                break
        except Exception:
            pass
    if not clicked:
        print("  لم يُعثر على زر تحقق ظاهر، سيكتمل الإرسال تلقائياً.")
    try:
        shot = PROFILE_DIR / "after_verify.png"
        page.screenshot(path=str(shot))
        print(f"  [تشخيص] صورة بعد التحقق: {shot}")
    except Exception:
        pass
    page.wait_for_timeout(2000)


def _strip_url(url: str) -> str:
    url = url.split("?")[0]
    if ";jsessionid=" in url:
        url = url.split(";jsessionid=")[0]
    return url.rstrip("/")


def _login_succeeded(page, login_path: str, timeout_sec: int = 90) -> bool:
    try:
        page.wait_for_timeout(6000)
    except Exception:
        return False
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if page.is_closed():
                return False
        except Exception:
            return False
        try:
            url = _strip_url(page.url)
        except Exception:
            return False
        if "/faces/home" in url:
            return True
        if url != login_path:
            return True
        try:
            user_present = page.locator("#pt1\\:unameInputId").count() > 0
        except Exception:
            user_present = True
        try:
            otp_visible = page.locator(OTP_BOXES[0]).count() > 0 and page.locator(OTP_BOXES[0]).is_visible()
        except Exception:
            otp_visible = False
        if not user_present and not otp_visible:
            _dump_page_state(page, "after_otp")
        try:
            page.wait_for_timeout(3000)
        except Exception:
            return False
    return False


def _dump_page_state(page, tag: str):
    try:
        shot = PROFILE_DIR / f"{tag}.png"
        page.screenshot(path=str(shot), full_page=False)
        print(f"  [تشخيص] صورة حالة الصفحة محفوظة: {shot}")
    except Exception:
        pass
    try:
        txt = page.inner_text("body")[:600].replace("\n", " ▸ ")
        print(f"  [تشخيص] نص الصفحة: {txt}")
    except Exception:
        pass


def _read_otp(cfg, base_uid: int = 0, page=None) -> str:
    otp_cfg = cfg["sso"]["otp"]
    email_addr = env("OTP_IMAP_EMAIL") or env("SMTP_SENDER")
    password = env("OTP_IMAP_PASSWORD") or env("SMTP_PASSWORD")
    if not email_addr:
        print("  لا يوجد بريد لقراءة رمز التحقق (OTP_IMAP_EMAIL في .env).")
        return ""
    if password:
        print(f"  محاولة قراءة الرمز عبر IMAP من {email_addr}...")
        try:
            code = fetch_otp(
                otp_cfg["imap_server"],
                otp_cfg["imap_port"],
                email_addr,
                password,
                otp_cfg["subject_keywords"],
                base_uid=base_uid,
                timeout_sec=20,
            )
            if code:
                return code
        except Exception as e:
            print(f"  فشل IMAP: {e}")
    print(f"  محاولة قراءة الرمز من صندوق البريد (OWA) {email_addr}...")
    code = read_otp_owa(email_addr, password or "", timeout_sec=otp_cfg.get("timeout_sec", 90), page=page)
    if code:
        return code
    print("  لم يصل رمز التحقق أو تعذر قراءته آلياً.")
    return ""


def _auto_login(page, cfg):
    sso = cfg["sso"]
    username = env("SSO_USERNAME")
    password = env("SSO_PASSWORD")
    if not username or not password:
        print("لا توجد بيانات دخول في ملف .env.")
        return False

    page.goto(sso["login_url"], wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    _type_into(page, sso["username_selector"], username)
    _type_into(page, sso["password_selector"], password)
    print("تم تعبئة الرقم الوظيفي وكلمة المرور.")

    email_addr = env("OTP_IMAP_EMAIL") or env("SMTP_SENDER")
    email_pw = env("OTP_IMAP_PASSWORD") or env("SMTP_PASSWORD")

    known_codes = set()
    mail_tab = None
    use_outlook = False
    if email_addr:
        try:
            from .outlook_reader import outlook_available, snapshot_codes as snapshot_codes_ol

            if outlook_available():
                known_codes = snapshot_codes_ol()
                print(f"  رموز OTP حديثة معروفة قبل الدخول (Outlook): {sorted(known_codes)}")
                use_outlook = True
            else:
                print("  Outlook المكتبي غير متاح — سيُستخدم صندوق البريد (OWA).")
        except Exception as e:
            print(f"  تعذر تجهيز قارئ Outlook ({e}) — سيُستخدم صندوق البريد (OWA).")
        if not use_outlook:
            try:
                from .owa_reader import open_mailbox_tab, snapshot_codes

                print(f"  تجهيز صندوق البريد (OWA) {email_addr} لحظة الدخول...")
                mail_tab = open_mailbox_tab(page, email_addr, email_pw, headless=False)
                if mail_tab is not None:
                    known_codes = snapshot_codes(mail_tab)
                    print(f"  رموز OTP قديمة معروفة قبل الدخول: {sorted(known_codes)}")
                else:
                    print("  تعذر فتح صندوق البريد للمعاينة.")
            except Exception as e:
                print(f"  تعذر تجهيز صندوق البريد: {e}")
                mail_tab = None

    retries = sso.get("captcha_retries", 3)
    for attempt in range(retries):
        if not _page_alive(page):
            return False
        if _captcha_visible(page):
            print("  الكابتشا ظاهرة، جارٍ حلها...")
            if not _solve_captcha(page):
                print("  تعذر حل الكابتشا.")
                return False
        _click_login(page)
        print("  تم الضغط على زر الدخول، بانتظار نافذة رمز التحقق...")
        page.wait_for_timeout(4000)
        try:
            url_after = _strip_url(page.url)
            login_path = _strip_url(sso["login_url"])
            if "/faces/home" in url_after or (url_after != login_path and url_after.startswith("https://")):
                print("  الدخول نجح بدون رمز تحقق!")
                return True
        except Exception:
            pass
        if _wait_for_otp_panel(page):
            break
        if attempt + 1 < retries:
            try:
                page.locator(CAPTCHA_REFRESH).click(force=True, timeout=5000)
            except Exception:
                pass
            print(f"  محاولة جديدة ({attempt + 2})...")
    else:
        print("تعذر الوصول لمرحلة رمز التحقق بعد عدة محاولات.")
        return False

    code = ""
    if use_outlook:
        print("  بانتظار وصول رمز التحقق الجديد في Outlook (يصل عادة خلال 30-50 ثانية)...")
        try:
            from .outlook_reader import wait_new_code as wait_new_code_ol

            code = wait_new_code_ol(known_codes, timeout_sec=90)
        except Exception as e:
            print(f"  خطأ في انتظار الرمز عبر Outlook: {e}")
    elif mail_tab is not None:
        print("  بانتظار وصول رمز التحقق الجديد في البريد (يصل عادة خلال 30-50 ثانية)...")
        try:
            from .owa_reader import wait_new_code

            code = wait_new_code(mail_tab, known_codes, timeout_sec=90, email_addr=email_addr, password=email_pw)
        except Exception as e:
            print(f"  خطأ في انتظار الرمز: {e}")
        finally:
            try:
                mail_tab.close()
            except Exception:
                pass
    if not code:
        code = _read_otp(cfg, 0, page=page)
    if code:
        _fill_otp(page, code)
    else:
        print("  أدخل رمز التحقق يدوياً في نافذة المتصفح (اقرأه من بريدك CoreSystems@alriyadh.gov.sa).")
        print("  سيُكتشف اكتمال الدخول تلقائياً خلال 3 دقائق...")

    login_path = _strip_url(sso["login_url"])
    ok = _login_succeeded(page, login_path, timeout_sec=sso.get("manual_timeout_sec", 90))
    try:
        print(f"  اكتمل الدخول، الرابط الحالي: {page.url}")
    except Exception:
        print("  اكتمل الدخول (أغلقت البوابة نافذة الدخول بعد النجاح).")
    if not ok:
        print("  تنبيه: لم يُلاحظ تحول صفحة الدخول إلى اللوحة — تحقق يدوياً من النافذة المفتوحة.")
    return ok


def _safe_click(page, selector: str):
    try:
        page.locator(selector).first.click(force=True, timeout=10000)
    except Exception:
        try:
            page.evaluate("(s) => { const el = document.querySelector(s); if (el) el.click(); }", selector)
        except Exception as e:
            print(f"  تعذر النقر على الزر: {e}")


def _click_login(page):
    try:
        page.evaluate("() => { const el = document.getElementById('clickLoginId'); if (el) el.click(); }")
    except Exception:
        _safe_click(page, "#clickLoginId")


def _page_alive(page) -> bool:
    try:
        page.title()
        return not page.is_closed()
    except Exception:
        return False


def _wait_for_enter_or_redirect(page, sso, timeout_sec: int) -> bool:
    login_path = _strip_url(sso["login_url"])
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not _page_alive(page):
            return False
        try:
            import msvcrt

            if msvcrt.kbhit():
                msvcrt.getch()
                return True
        except ImportError:
            pass
        try:
            if _strip_url(page.url) != login_path and page.url.startswith("https://"):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def login(auto: bool = False, inspect: bool = False, headless: bool = False):
    cfg = load_config()
    with sync_playwright() as p:
        context, page = _build_context(p, headless)
        sso = cfg["sso"]
        login_path = _strip_url(sso["login_url"])
        page.goto(sso["login_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        logged_in = is_logged_in(page)
        if logged_in:
            print("الدخول التلقائي عبر المصادقة الموحدة (IWA) — تم الدخول مباشرة.")
            save_session(context)
            context.close()
            return 0

        if inspect:
            _print_inputs(page)
            context.close()
            return 0

        if auto:
            logged_in = _auto_login(page, cfg)

        if not logged_in:
            print("سجّل الدخول في المتصفح المفتوح: الرقم الوظيفي + كلمة المرور + رمز التحقق.")
            print("بعد اكتمال الدخول، ارجع لهذه النافذة واضغط Enter (أو سيلتقط النظام الانتقال تلقائياً).")
            logged_in = _wait_for_enter_or_redirect(page, sso, sso.get("manual_timeout_sec", 600))

        if not logged_in:
            print("لم يتم اكتشاف اكتمال الدخول خلال المهلة.")
            try:
                context.close()
            except Exception:
                pass
            return 1

        save_session(context)
        print(f"تم حفظ الجلسة. الرابط الحالي: {page.url}")
        print("جلسة المتصفح محفوظة (ملف تعريف Chrome دائم) وستُستخدم في المرات القادمة.")
        try:
            context.close()
        except Exception:
            pass
        return 0

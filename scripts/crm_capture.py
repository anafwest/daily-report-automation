import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from .browser_session import open_persistent_context
from .config_loader import BASE_DIR, env, load_config

MAIN_URL = "https://crm.alriyadh.gov.sa/"
SEL_CASES = "[data-id='sitemap-entity-Cases_SubArea']"
FILTER_BTN = "[aria-label='Open advanced filtering panel']"


def _creds():
    u = env("CRM_USERNAME") or env("OTP_IMAP_EMAIL") or env("SSO_USERNAME")
    pw = env("CRM_PASSWORD")
    return u, pw


def _adfs_login(ctx, page):
    page = _pick_live(ctx, page)
    try:
        page.locator("#userNameInput").fill(_creds()[0])
        page.locator("#passwordInput").fill(_creds()[1])
        page.locator("#submitButton").click()
    except Exception:
        pass
    time.sleep(6)
    return _pick_live(ctx, page)


def _pick_live(ctx, page):
    try:
        for pg in ctx.pages:
            try:
                pg.title()
                return pg
            except Exception:
                pass
    except Exception:
        pass
    return page


def _wait_crm_ready(ctx, page, timeout_sec=60):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        page = _pick_live(ctx, page)
        try:
            if "/main.aspx" in page.url and "adfs" not in page.url:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def _select_view(page, name, retries=3):
    vs = page.locator("[data-id^='ViewSelector']").first
    for attempt in range(retries):
        try:
            vs.click(timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(4500)
        item = None
        for el in page.locator("[role='menuitem'], [role='option'], li, div").all():
            try:
                if el.is_visible() and el.inner_text().strip() == name:
                    item = el
                    break
            except Exception:
                pass
        if item is None:
            for el in page.locator("[role='menuitem'], [role='option'], li, div").all():
                try:
                    if el.is_visible() and name in el.inner_text():
                        item = el
                        break
                except Exception:
                    pass
        if item:
            try:
                item.click(timeout=5000)
            except Exception:
                item.dispatch_event("click")
            page.wait_for_timeout(1500)
            return True
        page.keyboard.press("Escape")
        page.wait_for_timeout(1200)
    return False


def _apply_date_filter(page, days_back=1):
    """فلترة تاريخ الإنشاء من (اليوم - days_back) حتى اليوم باستخدام عامل On or after."""
    crm_cfg = load_config()["report"].get("crm", {})
    date_field = crm_cfg.get("date_field", "تاريخ الإنشاء")
    fbtn = page.locator(FILTER_BTN).first
    fbtn.hover()
    page.wait_for_timeout(800)
    fbtn.click()
    page.wait_for_timeout(4000)

    page.locator("button:has-text('إضافة')").first.click(timeout=10000)
    page.wait_for_timeout(3000)

    page.locator("[aria-label='field selector']").last.click(timeout=10000)
    page.wait_for_timeout(2500)
    page.locator(f"[aria-label='{date_field}']").last.click(timeout=10000)
    page.wait_for_timeout(2500)

    page.locator("[aria-label='عامل التشغيل']").last.click(timeout=10000)
    page.wait_for_timeout(2500)
    page.locator("[aria-label='On or after']").first.click(timeout=10000)
    page.wait_for_timeout(3000)

    start = datetime.now() - timedelta(days=int(days_back))
    value = start.strftime("%d/%m/%Y")
    v = page.locator("[aria-label='القيمة']").first
    v.click(timeout=8000)
    page.wait_for_timeout(500)
    page.keyboard.press_sequentially(value)
    page.wait_for_timeout(1500)

    page.locator("[aria-label='Apply the current advanced filters']").first.click(timeout=10000)
    page.wait_for_timeout(9000)
    print(f"طُبّق فلتر التاريخ: من {value} (اليوم وأمس)")


def capture_report(view_name=None, headless=False) -> str:
    cfg = load_config()
    rcfg = cfg["report"]
    crm = rcfg.get("crm", {})
    view_name = view_name or crm.get("view_name", "التقرير الشامل")
    fallback = crm.get("fallback_view_name", "تقرير كافة الطلبات")
    export_btn = crm.get("export_button", "تصدير إلى Excel")
    download_sec = int(crm.get("download_timeout_sec", 600))
    days_back = int(crm.get("date_days_back", 1))
    out_dir = BASE_DIR / rcfg.get("download_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    u, pw = _creds()
    if not u or not pw:
        print("تعذر الالتقاط: اضبط CRM_USERNAME و CRM_PASSWORD في .env")
        return ""

    with sync_playwright() as p:
        ctx, page = open_persistent_context(p, headless=headless)
        try:
            page.goto(crm.get("url", MAIN_URL), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            page = _pick_live(ctx, page)
            if "adfs/ls" in page.url:
                print("تسجيل الدخول إلى علاقات العملاء (ADFS)...")
                page = _adfs_login(ctx, page)
            if not _wait_crm_ready(ctx, page):
                print("تعذر الوصول إلى علاقات العملاء.")
                return ""
            page = _pick_live(ctx, page)
            page.wait_for_timeout(6000)
            print("فتح قسم الطلبات...")
            page.locator(SEL_CASES).first.click(timeout=20000)
            page.wait_for_timeout(8000)

            if not _select_view(page, view_name):
                print(f"العرض '{view_name}' غير متاح — استخدام البديل '{fallback}'.")
                if not _select_view(page, fallback):
                    print("لا يوجد عرض متاح للتصدير.")
                    return ""
            print("العرض محدد، انتظار تحميل القائمة...")
            page.wait_for_timeout(8000)

            if crm.get("apply_date_filter", True):
                _apply_date_filter(page, days_back)

            print(f"النقر على {export_btn}...")
            btn = page.locator(f"button:has-text('{export_btn}')").first
            btn.click(timeout=15000)
            page.wait_for_timeout(4000)

            static = crm.get("static_worksheet", "ورقة عمل ثابتة")
            try:
                opt = page.locator(f"[role='menuitem']:has-text('{static}')").first
                if opt.count() and opt.is_visible():
                    print("اختيار ورقة عمل ثابتة...")
                    opt.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

            today = datetime.now().strftime("%Y-%m-%d")
            out_path = out_dir / f"تقرير_{today}.xlsx"
            print("بانتظار اكتمال التصدير والتحميل (قد يستغرق دقائق)...")
            with page.expect_download(timeout=download_sec * 1000) as dl_info:
                try:
                    page.locator("button:has-text('تنزيل'), button:has-text('Download')").first.click(timeout=8000)
                except Exception:
                    pass
            dl = dl_info.value
            dl.save_as(str(out_path))
            print(f"تم تحميل التقرير: {out_path}")
            return str(out_path)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return ""

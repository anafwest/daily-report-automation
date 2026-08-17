import time, sys, os
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from .browser_session import open_persistent_context
from .config_loader import BASE_DIR, env, load_config

MAIN_URL = "https://crm.alriyadh.gov.sa/"


def _creds():
    u = env("CRM_USERNAME") or env("OTP_IMAP_EMAIL") or env("SSO_USERNAME")
    pw = env("CRM_PASSWORD")
    return u, pw


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


def _adfs_login(ctx, page):
    page = _pick_live(ctx, page)
    u, pw = _creds()
    if u and pw:
        print("  ملء بيانات ADFS...")
        try:
            page.locator("#userNameInput").wait_for(state="visible", timeout=15000)
            page.locator("#userNameInput").fill(u)
            page.locator("#passwordInput").fill(pw)
            page.locator("#submitButton").click()
            print("  تم إرسال بيانات الدخول.")
        except Exception as e:
            print(f"  خطأ ADFS: {e}")
    else:
        print("  لا توجد بيانات ADFS — الاعتماد على IWA...")
    return _pick_live(ctx, page)


def _wait_crm_ready(ctx, page, timeout_sec=90):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        page = _pick_live(ctx, page)
        try:
            url = page.url
            if "/main.aspx" in url and "adfs" not in url:
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
                if el.is_visible() and name in el.inner_text().strip():
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
    crm_cfg = load_config()["report"].get("crm", {})
    date_field = crm_cfg.get("date_field", "تاريخ الإنشاء")
    fbtn = page.locator("[aria-label='Open advanced filtering panel']").first
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
    page.keyboard.type(value, delay=30)
    page.wait_for_timeout(1500)

    page.locator("[aria-label='Apply the current advanced filters']").first.click(timeout=10000)
    page.wait_for_timeout(9000)
    print(f"  طُبّق فلتر التاريخ: من {value}")


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

    with sync_playwright() as p:
        ctx, page = open_persistent_context(p, headless=headless)
        try:
            # الخطوة 1: فتح CRM
            print("1. فتح علاقات العملاء...")
            page.goto(crm.get("url", MAIN_URL), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)

            # الخطوة 2: تسجيل دخول ADFS إذا لزم
            page = _pick_live(ctx, page)
            if "adfs" in page.url:
                print("2. تسجيل الدخول عبر ADFS...")
                page = _adfs_login(ctx, page)
            else:
                print("2. لا حاجة لـ ADFS (IWA نشط).")

            # الخطوة 3: انتظار تحميل CRM
            print("3. انتظار تحميل CRM...")
            if not _wait_crm_ready(ctx, page, timeout_sec=90):
                print("  تعذر الوصول إلى علاقات العملاء.")
                return ""
            page = _pick_live(ctx, page)
            page.wait_for_timeout(15000)
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(10000)
            page = _pick_live(ctx, page)

            # إذا الصفحة لا تزال في apps، انتقل مباشرة للعرض الصحيح
            if "pagetype=apps" in page.url or "viewid=" not in page.url:
                view_url = "https://crm.alriyadh.gov.sa/main.aspx?pagetype=entitylist&etn=incident&viewid=c55cdaec-d5f5-f011-8504-0050568118ac&viewType=4230"
                print(f"  الانتقال المباشر للعرض...")
                page.goto(view_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(20000)
                try:
                    page.wait_for_load_state("networkidle", timeout=60000)
                except Exception:
                    pass
                page.wait_for_timeout(10000)
                page = _pick_live(ctx, page)

            print(f"  العنوان: {page.title()}")
            print(f"  الرابط: {page.url[:120]}")

            # الخطوة 4: التحقق من العرض / تحديده
            current_title = page.title()
            if view_name in current_title or "التقرير الشامل" in current_title:
                print(f"4. العرض '{view_name}' محمل مسبقاً.")
            else:
                print(f"4. محاولة تحديد العرض '{view_name}'...")
                if not _select_view(page, view_name):
                    print(f"  '{view_name}' غير متاح — استخدام '{fallback}'.")
                    if not _select_view(page, fallback):
                        print("  لا يوجد عرض متاح.")
                        return ""

            # الخطوة 5: فلترة التاريخ
            if crm.get("apply_date_filter", True):
                print("5. تطبيق فلتر التاريخ...")
                _apply_date_filter(page, days_back)
            else:
                print("5. تخطي فلتر التاريخ.")

            # الخطوة 6: تصدير إلى Excel
            print(f"6. النقر على '{export_btn}'...")
            btn = page.locator(f"button:has-text('{export_btn}')").first
            btn.click(timeout=15000)
            page.wait_for_timeout(4000)

            static = crm.get("static_worksheet", "ورقة عمل ثابتة")
            try:
                opt = page.locator(f"[role='menuitem']:has-text('{static}')").first
                if opt.count() and opt.is_visible():
                    print("  اختيار ورقة عمل ثابتة...")
                    opt.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

            # الخطوة 7: تحميل الملف
            today = datetime.now().strftime("%Y-%m-%d")
            out_path = out_dir / f"تقرير_{today}.xlsx"
            print("7. بانتظار اكتمال التصدير والتحميل...")
            with page.expect_download(timeout=download_sec * 1000) as dl_info:
                try:
                    page.locator("button:has-text('تنزيل'), button:has-text('Download')").first.click(timeout=8000)
                except Exception:
                    pass
            dl = dl_info.value
            dl.save_as(str(out_path))
            print(f"  تم تحميل التقرير: {out_path}")
            return str(out_path)
        except Exception as e:
            print(f"خطأ: {e}")
            try:
                page = _pick_live(ctx, page)
                page.screenshot(path=str(out_dir / "crm_error.png"))
            except Exception:
                pass
            return ""
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return ""

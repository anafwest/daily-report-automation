from .config_loader import BASE_DIR

PROFILE_DIR = BASE_DIR / ".browser_profile"
CHROME_PROFILE = PROFILE_DIR / "chrome_profile"
EDGE_PROFILE = CHROME_PROFILE


def open_persistent_context(playwright, headless=False):
    ctx = playwright.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE),
        channel="chrome",
        headless=headless,
        locale="ar-SA",
        viewport={"width": 1600, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def profile_exists() -> bool:
    return (CHROME_PROFILE / "Default").exists() or CHROME_PROFILE.exists()

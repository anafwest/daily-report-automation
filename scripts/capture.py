import sys
import time

import pandas as pd
from playwright.sync_api import sync_playwright

from .config_loader import BASE_DIR, load_config
from .login import PROFILE_DIR


def _table_to_df(page, table_el) -> pd.DataFrame:
    rows = table_el.locator("tr").all()
    header_cells = []
    data_rows = []

    for i, tr in enumerate(rows):
        tag = tr.locator(":scope > th, :scope > td")
        cells = tag.all()
        texts = [c.inner_text().strip() for c in cells]
        if not texts:
            continue
        if i == 0:
            header_cells = texts
        else:
            data_rows.append(texts)

    if header_cells and data_rows and len(data_rows[0]) == len(header_cells):
        return pd.DataFrame(data_rows, columns=header_cells)
    if data_rows:
        width = max(len(r) for r in data_rows)
        cols = [f"عمود {j+1}" for j in range(width)]
        return pd.DataFrame(data_rows, columns=cols)
    return pd.DataFrame()


def capture_tables(url: str = "", headless: bool = False, max_wait_sec: int = 15):
    cfg = load_config()
    if not (PROFILE_DIR / "session.json").exists():
        print("لا توجد جلسة محفوظة. نفّذ أولاً:  python main.py login")
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=headless)
        context = browser.new_context(storage_state=str(PROFILE_DIR / "session.json"), locale="ar-SA")
        page = context.new_page()

        if url:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(max_wait_sec * 1000)
        else:
            try:
                url = input("الصق رابط التقرير إذا كان معروفاً (أو Enter للالتقاط من الشاشة الحالية): ").strip()
            except EOFError:
                url = ""
            if url:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(max_wait_sec * 1000)
            else:
                print("افتح التقرير المطلوب في المتصفح، وعند ظهور النتائج اضغط Enter في هذه النافذة...")
                input()
                page.wait_for_timeout(2000)

        tables = page.locator("table").all()
        print(f"عدد الجداول المكتشفة في الصفحة: {len(tables)}")
        dfs = []
        for idx, tbl in enumerate(tables, start=1):
            df = _table_to_df(page, tbl)
            if not df.empty:
                print(f"  جدول {idx}: {df.shape[0]} صف × {df.shape[1]} عمود")
                dfs.append((f"جدول_{idx}", df))

        for f_idx, frame in enumerate(page.frames, start=1):
            if frame == page.main_frame:
                continue
            try:
                ftables = frame.locator("table").all()
            except Exception:
                continue
            for tbl in ftables:
                df = _table_to_df(frame, tbl)
                if not df.empty:
                    print(f"  إطار {f_idx} - جدول: {df.shape[0]} صف × {df.shape[1]} عمود")
                    dfs.append((f"إطار{f_idx}", df))

        if not dfs:
            print("لم يتم العثور على بيانات جدولية. تأكد من فتح التقرير وظهور النتائج.")

        browser.close()
        return dfs


def click_export_button(url: str = "", headless: bool = False):
    cfg = load_config()
    keywords = cfg["report"].get("export_button_keywords", ["تصدير", "Excel", "تحميل"])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=headless)
        context = browser.new_context(storage_state=str(PROFILE_DIR / "session.json"), locale="ar-SA")
        page = context.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(10000)

        for kw in keywords:
            btn = page.locator(f"button:has-text('{kw}'), a:has-text('{kw}')").first
            if btn.count() > 0 and btn.is_visible():
                print(f"تم العثور على زر '{kw}' والنقر عليه.")
                with page.expect_download(timeout=60000) as dl:
                    btn.click()
                download = dl.value
                out = BASE_DIR / "output" / download.suggested_filename
                download.save_as(str(out))
                print(f"تم تنزيل الملف: {out}")
                browser.close()
                return str(out)
        print("لم يتم العثور على زر تصدير/تحميل. جرّب وضع التقاط الجداول: python main.py capture")
        browser.close()
        return None

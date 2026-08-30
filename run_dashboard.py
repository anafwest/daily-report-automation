# -*- coding: utf-8 -*-
"""
تشغيل لوحة تحليل الأداء (خادم Flask محلي + فتح المتصفح تلقائياً)
استخدام: python run_dashboard.py [--port 8080] [--open]
المنفذ الافتراضي: 8080 — إن كان مشغولاً يُجرّب 8081..8099
"""
import argparse
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _find_free_port(start: int) -> int:
    for p in range(start, start + 100):
        if _port_free(p):
            return p
    return start


def main():
    parser = argparse.ArgumentParser(description="لوحة تحليل أداء التقارير اليومية")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-open", action="store_true", help="لا تفتح المتصفح تلقائياً")
    args = parser.parse_args()

    port = _find_free_port(args.port)

    from scripts.performance_analysis import _run_server

    if not args.no_open:
        def _open():
            import time
            time.sleep(3)
            webbrowser.open(f"http://localhost:{port}/")
        threading.Thread(target=_open, daemon=True).start()

    print("=" * 55)
    print(f"لوحة تحليل الأداء على: http://localhost:{port}/")
    print("اضغط Ctrl+C للإيقاف")
    print("=" * 55)
    try:
        _run_server(port)
    except KeyboardInterrupt:
        print("\nتم إيقاف اللوحة.")


if __name__ == "__main__":
    main()

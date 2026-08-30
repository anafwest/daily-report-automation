# -*- coding: utf-8 -*-
"""
أداة تحليل الأداء لنظام التقارير اليومية
=========================================
أداة CLI (سطر أوامر) تحلّل أداء النظام على جهاز التعديل ضمن نطاق آمن وواقعي:
  1. bench        - قياس زمن مراحل المعالجة على ملف تقرير محدد
  2. config-check - فحص صحة/انحراف إعدادات config.json و run_daily.bat عن GitHub (قراءة فقط)
  3. heavy        - تحليل استاتيكي للنقاط الثقيلة في الكود
  4. output       - تقرير من ملفات output الموجودة محلياً (مع تنبيه القِدَم)
  5. all          - تشغيل الكل معاً

حدود صريحة:
- لا ترسل أي بريد، لا تعدّل ملفات إنتاج، لا تلمس الجهاز الأساسي، لا ترفع لـ GitHub.
- إثبات "فعلية السحب والإرسال" الحقيقية لا يمكن من هنا؛ يقتضي بيانات الجهاز الأساسي
  أو صندوق البريد الفعلي. هذه الأداة تعطي مؤشرات محلية فقط.

الاستخدام:
    python main.py perf config-check
    python main.py perf heavy
    python main.py perf bench --file output/تقرير_التاريخ.xlsx
    python main.py perf output
    python main.py perf all
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config_loader import BASE_DIR, load_config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PERF_LOG = BASE_DIR / "output" / "سجل_الأداء.csv"


def _noarg(fn):
    def _wrapper(_args):
        return fn()
    return _wrapper


def _load_config_fresh() -> dict:
    return load_config()


def _t(sec: float) -> str:
    return f"{sec:.2f} ثانية"


# ---------------------------------------------------------------
# البند 1: قياس زمن المراحل (Benchmark)
# ---------------------------------------------------------------
def _run_bench(file: str) -> int:
    from . import split_by_dept, validate_report

    path = Path(file)
    if not path.exists():
        print(f"🔴 الملف غير موجود: {path}")
        return 1

    print("=" * 60)
    print(f"قياس زمن معالجة: {path.name}")
    print("=" * 60)

    results = {}
    t0 = time.time()
    df, validation = validate_report.load_report(str(path))
    results["قراءة الملف + فحصه"] = time.time() - t0
    print(f"  قراءة + فحص: {_t(results['قراءة الملف + فحصه'])}  (سجلات: {validation.get('rows', len(df))})")

    t0 = time.time()
    filtered = split_by_dept.apply_filters(df)
    results["فلترة الحالة/المنطقة"] = time.time() - t0
    print(f"  فلترة: {_t(results['فلترة الحالة/المنطقة'])}  (بعد الفلترة: {len(filtered)})")

    t0 = time.time()
    result = split_by_dept.split_by_department(str(path))
    results["التقسيم وبناء ملفات الإدارات"] = time.time() - t0
    print(f"  تقسيم: {_t(results['التقسيم وبناء ملفات الإدارات'])}  (إدارات: {len(result)})")

    total = sum(results.values())
    results["الإجمالي"] = total
    print(f"  الإجمالي: {_t(total)}")

    # حفظ السجل للتتبع عبر الأيام
    try:
        perf_log = Path(PERF_LOG)
        perf_log.parent.mkdir(parents=True, exist_ok=True)
        row = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "file": path.name,
               "rows": int(len(df)),
               "depts": len(result)}
        row.update({f"sec_{k}": f"{v:.3f}" for k, v in results.items()})
        write_header = not perf_log.exists()
        pd.DataFrame([row]).to_csv(perf_log, mode="a", header=write_header, index=False, encoding="utf-8-sig")
        print(f"\nسُجّلت النتائج في: {PERF_LOG}")
    except Exception as e:
        print(f"تنبيه: تعذر حفظ سجل الأداء: {e}")

    return 0


# ---------------------------------------------------------------
# البند 2: فحص صحة الإعدادات عن GitHub (قراءة فقط)
# ---------------------------------------------------------------
def _git_show_remote(blob: str) -> str:
    cmd = ["git", "show", f"origin/main:{blob}"]
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return r.stdout
        return ""
    except Exception:
        return ""


def _run_config_check() -> int:
    git = "C:\\Users\\HPProBook440G9\\AppData\\Local\\Programs\\Git\\bin\\git.exe"
    print("=" * 60)
    print("فحص صحة الإعدادات (محلي مقابل GitHub - قراءة فقط)")
    print("=" * 60)

    local_cfg = _load_config_fresh()

    # جلب نسخة GitHub (قراءة فقط، بدون سحب/تعديل)
    try:
        r = subprocess.run([git, "-C", str(BASE_DIR), "show", "origin/main:config.json"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60)
        remote_cfg = dict
        import json as _json
        remote_cfg = _json.loads(r.stdout)
        print("  تم قراءة config.json من GitHub (أحدث commit).")
    except Exception as e:
        print(f"  ⚠️ تعذر قراءة config.json من GitHub: {e} — الفحص جزئي فقط.")
        remote_cfg = None

    def _cmp(label, local_val, remote_val, warn_only=False):
        l = _norm(local_val)
        if remote_cfg is None:
            print(f"  {"🟢" if not warn_only else "🟡"} {label}: {l or '—'}")
            return
        r = _norm(remote_val)
        if l == r:
            print(f"  🟢 {label}: {l or '—'}")
        else:
            print(f"  {'🟡' if warn_only else '🔴'} {label}: محلي={l or '—'} | GitHub={r or '—'}")

    def _norm(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    print("\n[إعدادات حرجة للإنتاج]")
    _cmp("summary_only", local_cfg["email"].get("summary_only"),
         remote_cfg["email"].get("summary_only") if remote_cfg else "")
    _cmp("test_mode.enabled", local_cfg["test_mode"].get("enabled"),
         remote_cfg["test_mode"].get("enabled") if remote_cfg else "")
    _cmp("crm.enabled", local_cfg["report"]["crm"].get("enabled"),
         remote_cfg["report"]["crm"].get("enabled") if remote_cfg else "")
    _cmp("send_via", local_cfg["email"].get("send_via"),
         remote_cfg["email"].get("send_via") if remote_cfg else "")
    _cmp("scheduler.time", local_cfg["scheduler"].get("time"),
         remote_cfg["scheduler"].get("time") if remote_cfg else "")

    print("\n[أعمد رئيسية]")
    _cmp("department_column", local_cfg["report"].get("department_column"),
         remote_cfg["report"].get("department_column") if remote_cfg else "")
    _cmp("status_column", local_cfg["report"].get("status_column"),
         remote_cfg["report"].get("status_column") if remote_cfg else "")

    # run_daily.bat محلي vs GitHub
    bat_local = (BASE_DIR / "run_daily.bat").read_text("utf-8", errors="replace")
    bat_remote = _git_show_remote("run_daily.bat") or ""
    print("\n[run_daily.bat]")
    print("  محلي  : " + " | ".join(l.strip() for l in bat_local.strip().splitlines() if l.strip())[:200])
    if bat_remote:
        print("  GitHub: " + " | ".join(l.strip() for l in bat_remote.strip().splitlines() if l.strip())[:200])

    print("\n" + "-" * 60)
    print("ملاحظة: اختلاف الإعدادات بين جهاز التعديل والجهاز الأساسي أمر متوقع وقد يكون مقصوداً.")
    print("هذا الفحص مؤشر محلي فقط؛ ليثبت فعلية السحب والإرسال يلزم بيانات الجهاز الأساسي.")
    return 0


# ---------------------------------------------------------------
# البند 3: تحليل استاتيكي للنقاط الثقيلة
# ---------------------------------------------------------------
def _run_heavy() -> int:
    import re

    print("=" * 60)
    print("تحليل استاتيكي للنقاط الثقيلة (قراءة كود فقط)")
    print("=" * 60)

    findings = []

    def _scan(path: Path, label: str):
        txt = path.read_text("utf-8", errors="replace")
        lines = txt.splitlines()
        # 1) كثرة استدعاء load_config داخل حلقات
        calls = [i + 1 for i, l in enumerate(lines) if re.search(r"load_config\s*\(", l)]
        if calls:
            findings.append(f"{label}: استدعاءات load_config عند الأسطر {calls} — يُفضّل caching.")

        # 2) قراءة ملف Excel أكثر من مرة
        reads = [i + 1 for i, l in enumerate(lines) if re.search(r"pd\.read_excel|read_excel\(", l)]
        if len(reads) > 1:
            findings.append(f"{label}: قراءات متعددة للملف عند الأسطر {reads} — يُفضّل قراءة DataFrame مرة واحدة وتمريره.")

        # 3) كتابة Excel في حلقة
        writes = [i + 1 for i, l in enumerate(lines) if re.search(r"save_dataframes\s*\(|\bto_excel\s*\(", l)]
        if len(writes) > 3 and any("for " in l for l in lines):
            findings.append(f"{label}: كتابات Excel متعددة ({len(writes)}) قد يكون داخل حلقة (أسطر {writes}).")

    for name in ["split_by_dept.py", "send_email.py", "owa_send.py", "main.py"]:
        p = Path(__file__).parent / name
        if p.exists():
            _scan(p, name)

    if findings:
        print("\nالنقاط المكتشفة:")
        for f in findings:
            print(f"  - {f}")
    else:
        print("\nلا توجد نقاط ثقيلة واضحة في الملفات المفحوصة.")

    print("\nملاحظة: هذا تحليل استاتيكي فقط، قد يحتاج تحققاً يدوياً قبل أي تعديل.")
    return 0


# ---------------------------------------------------------------
# البند 4: تقرير من ملفات output الموجودة محلياً
# ---------------------------------------------------------------
def _run_output() -> int:
    print("=" * 60)
    print("تقرير الملفات الموجودة في output/ (محلي فقط)")
    print("=" * 60)

    out = BASE_DIR / "output"
    if not out.exists():
        print("لا يوجد مجلد output/.")
        return 0

    now = datetime.now()

    # سجل التشغيل
    log = None
    for p in out.glob("*.csv"):
        if "سجل" in p.name:
            log = p
            break
    if log:
        df = pd.read_csv(log)
        print(f"\n[سجل التشغيل: {log.name}]  (آخر تعديل: {log.stat().st_mtime and _ago(log, now)})")
        if len(df):
            tail = df.tail(8)
            print(tail[["run_id", "date", "status"]].to_string(index=False) if "status" in df.columns else tail.to_string(index=False))
    else:
        print("\n⚠️ لا يوجد ملف سجل تشغيل في output/ — قد يعني عدم تشغيل الدورة على هذا الجهاز.")

    # ملخص الإرسال
    for f in out.glob("ملخص_*"):
        if f.suffix == ".xlsx":
            ago = _ago(f, now)
            print(f"\n[ملخص الإرسال: {f.name}] آخر تعديل: {ago}")
            break

    # أقدم/أحدث ملف تقرير
    reports = [p for p in out.glob("*.xlsx") if p.name not in ("ملخص_الإرسال.xlsx", "تقرير_التشغيل_اليومي.xlsx")]
    if reports:
        newest = max(reports, key=lambda p: p.stat().st_mtime)
        oldest = min(reports, key=lambda p: p.stat().st_mtime)
        print(f"\nأحدث ملف: {newest.name} ({_ago(newest, now)})")
        print(f"أقدم ملف: {oldest.name} ({_ago(oldest, now)})")
    else:
        print("\n⚠️ لا توجد ملفات تقرير خام هنا.")

    print("\nتنبيه: هذه ملفات هذا الجهاز (التعديل) فقط، وليست دليلاً على تشغيل الجهاز الأساسي.")
    return 0


def _ago(p: Path, now: datetime) -> str:
    try:
        mt = datetime.fromtimestamp(p.stat().st_mtime)
        days = (now - mt).days
        if days < 1:
            return "أقل من يوم"
        if days > 30:
            return f"قبل {days // 30} شهر"
        return f"قبل {days} يوم"
    except Exception:
        return "غير معروف"


# ---------------------------------------------------------------
# البند 5: تشغيل الكل
# ---------------------------------------------------------------
def _run_all() -> int:
    print("##########  أداة تحليل الأداء - تشغيل شامل  ##########\n")
    code = 0
    for fn, label, arg in [
        (_run_heavy, "التحليل الاستاتيكي", None),
        (_run_config_check, "فحص الإعدادات", None),
        (_run_output, "ملفات output", None),
    ]:
        print(f"\n##########  {label}  ##########")
        try:
            code |= fn(arg) if arg else fn()
        except Exception as e:
            print(f"خطأ أثناء {label}: {e}")
        print()
    return code


PARSER_HELP = "تحليل أداء النظام (قراءة فقط، لا يرسل ولا يعدّل إنتاج)."


def add_parser(sub):
    p = sub.add_parser("perf", help=PARSER_HELP)
    s = p.add_subparsers(dest="perf_cmd", required=True)
    s.add_parser("heavy", help="تحليل استاتيكي للنقاط الثقيلة").set_defaults(perf_fn=_noarg(_run_heavy))
    s.add_parser("config-check", help="فحص صحة الإعدادات عن GitHub").set_defaults(perf_fn=_noarg(_run_config_check))
    s.add_parser("output", help="تقرير من ملفات output الموجودة").set_defaults(perf_fn=_noarg(_run_output))
    s.add_parser("all", help="تشغيل الكل معاً").set_defaults(perf_fn=_noarg(_run_all))
    b = s.add_parser("bench", help="قياس زمن المراحل على ملف تقرير")
    b.add_argument("--file", required=True, help="مسار ملف التقرير الخام")
    b.set_defaults(perf_fn=lambda args: _run_bench(args.file))
    srv = s.add_parser("server", help="تشغيل لوحة تحكم ويب محلية (Flask)")
    srv.add_argument("--port", type=int, default=8080, help="منفذ الخادم المحلي (افتراضي 8080)")
    srv.set_defaults(perf_fn=lambda args: _run_server(args.port))
    return p


# ---------------------------------------------------------------
# البند 6: لوحة تحكم ويب (Flask) — محلية، قراءة/عرض فقط
# ---------------------------------------------------------------
def _collect_dashboard() -> dict:
    """يجمع كل البيانات المطلوبة للوحة (بدون تشغيل عمليات ثقيلة مطلوبة يدوياً)."""
    cfg = load_config()
    data = {"config": cfg, "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    logs = []
    out = BASE_DIR / "output"
    log = None
    if out.exists():
        for p in out.glob("*.csv"):
            if "سجل" in p.name:
                log = p
                break
    if log:
        try:
            df = pd.read_csv(log)
            logs = df.tail(10).to_dict("records")
        except Exception:
            logs = []
    data["logs"] = logs
    data["log_exists"] = log is not None
    data["log_age_days"] = _age_days(log) if log else None

    files = []
    if out.exists():
        for p in sorted(out.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:15]:
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size, "age_days": _age_days(p)})
    data["files"] = files

    perf_rows = []
    if Path(PERF_LOG).exists():
        try:
            pde = pd.read_csv(PERF_LOG)
            perf_rows = pde.tail(10).to_dict("records")
        except Exception:
            perf_rows = []
    data["perf_rows"] = perf_rows

    status_items = []
    try:
        status_items = _gather_config_checks()
    except Exception as e:
        status_items = [{"label": "خطأ في فحص الإعدادات", "local": "", "remote": "", "same": False,
                         "codepoint": "red"}]
    data["checks"] = status_items

    return data


def _age_days(p: Path):
    try:
        return (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).days
    except Exception:
        return None


def _gather_config_checks() -> list:
    import json as _json

    cfg = load_config()
    items = []
    try:
        r = subprocess.run(["git", "-C", str(BASE_DIR), "show", "origin/main:config.json"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60)
        remote_cfg = _json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        remote_cfg = None

    def _norm(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    keys = [
        ("email.summary_only", "summary_only"),
        ("test_mode.enabled", "test_mode.enabled"),
        ("report.crm.enabled", "crm.enabled"),
        ("email.send_via", "send_via"),
        ("scheduler.time", "scheduler.time"),
        ("report.department_column", "department_column"),
        ("report.status_column", "status_column"),
    ]
    for path, label in keys:
        parts = path.split(".")
        lv = cfg
        rv = None
        try:
            for part in parts:
                lv = lv[part]
            if remote_cfg is not None:
                rv = remote_cfg
                for part in parts:
                    rv = rv[part]
        except Exception:
            lv = ""
            rv = None
        l = _norm(lv)
        r = _norm(rv) if remote_cfg is not None else ""
        same = (l == r) if remote_cfg is not None else True
        items.append({"label": label, "local": l, "remote": r,
                      "codepoint": "green" if same else "red", "same": same})
    return items


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>لوحة تحليل الأداء — التقارير اليومية</title>
<style>
  :root { --green:#16a34a; --red:#dc2626; --amber:#d97706; --bg:#0f172a; --card:#1e293b; --muted:#94a3b8; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Segoe UI",Tahoma,Arial,sans-serif; background:var(--bg); color:#e2e8f0; }
  header { padding:20px 28px; background:linear-gradient(135deg,#1e3a8a,#0f172a); border-bottom:1px solid #334155; }
  header h1 { margin:0; font-size:22px; }
  header p { margin:6px 0 0; color:var(--muted); font-size:13px; }
  .wrap { padding:24px 28px; max-width:1100px; margin:0 auto; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:16px; margin-top:18px; }
  .card { background:var(--card); border:1px solid #334155; border-radius:12px; padding:18px; }
  .card h2 { margin:0 0 12px; font-size:16px; color:#cbd5e1; }
  .kpi { font-size:30px; font-weight:700; }
  .green{ color:var(--green);} .red{ color:var(--red);} .amber{ color:var(--amber);}
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:right; padding:8px 10px; border-bottom:1px solid #334155; }
  th { color:var(--muted); font-weight:600; }
  .badge { display:inline-block; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
  .badge.green{ background:rgba(22,163,74,.15);} .badge.red{ background:rgba(220,38,38,.15);} .badge.amber{ background:rgba(217,119,6,.15);}
  .btn { margin-top:16px; padding:10px 18px; border:none; border-radius:8px; background:#2563eb; color:#fff;
         font-size:14px; cursor:pointer; }
  .btn:hover{ background:#1d4ed8; }
  .note { margin-top:16px; padding:12px; border-radius:8px; background:#1e3a8a22; border:1px solid #334155;
          color:var(--muted); font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>📊 لوحة تحليل أداء نظام التقارير اليومية</h1>
  <p>آخر تحديث: {now} — محلية فقط (قراءة/عرض، لا ترسل ولا تعدّل إنتاج)</p>
</header>
<div class="wrap">
  <button class="btn" onclick="location.reload()">🔄 تحديث</button>
  <div class="grid">
    <div class="card"><h2>سجل التشغيل</h2>{log_kpi}</div>
    <div class="card"><h2>ملفات output</h2><div class="kpi">{file_count}</div>
      <div style="color:var(--muted);font-size:13px">أحدثها: {newest_file}</div></div>
    <div class="card"><h2>سجلات الأداء</h2><div class="kpi">{perf_count}</div>
      <div style="color:var(--muted);font-size:13px">Benchmark في output/سجل_الأداء.csv</div></div>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>🔍 فحص صحة الإعدادات (محلي مقابل GitHub)</h2>
    <table><tr><th>البند</th><th>محلي</th><th>GitHub</th><th>الحالة</th></tr>{checks_rows}</table>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>🕒 آخر التشغيلات (من سجل_التشغيل.csv)</h2>
    <table><tr><th>Run ID</th><th>التاريخ</th><th>مرسلة</th><th>فاشلة</th><th>الحالة</th></tr>{log_rows}</table>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>🧪 قياسات الأداء المحفوظة</h2>
    <table><tr><th>التاريخ</th><th>الملف</th><th>سجلات</th><th>الإجمالي (ث)</th></tr>{perf_rows}</table>
  </div>

  <div class="note">
    ⚠️ هذه اللوحة تعرض بيانات <b>هذا الجهاز (جهاز التعديل)</b> فقط. إثبات "فعلية السحب والإرسال"
    الحقيقية يقتضي بيانات الجهاز الأساسي. لا تُرفع أي بيانات إلى GitHub من هذه الصفحة.
  </div>
</div>
</body>
</html>
"""


def _render_dashboard() -> str:
    d = _collect_dashboard()

    if d["log_exists"]:
        last = d["logs"][-1] if d["logs"] else {}
        st = str(last.get("status", ""))
        cls = "green" if st == "success" else ("red" if st == "fail" else "amber")
        age = d.get("log_age_days")
        log_kpi = (f'<div class="kpi {cls}" style="font-size:20px">{st}</div>'
                   f'<div style="color:var(--muted);font-size:13px">آخر تعديل قبل {age if age is not None else "?"} يوم</div>')
    else:
        log_kpi = '<div class="kpi red" style="font-size:18px">لا يوجد سجل</div>'

    checks_rows = ""
    for c in d["checks"]:
        badge = f'<span class="badge {c["codepoint"]}">{"مطابق" if c.get("same") else "مختلف"}</span>'
        checks_rows += (f'<tr><td>{c["label"]}</td><td>{c["local"] or "—"}</td>'
                        f'<td>{c["remote"] or "—"}</td><td>{badge}</td></tr>')

    log_rows = ""
    for r in d["logs"]:
        st = str(r.get("status", ""))
        badge = f'<span class="badge {"green" if st=="success" else ("red" if st=="fail" else "amber")}">{st}</span>'
        log_rows += (f'<tr><td>{r.get("run_id","")}</td><td>{r.get("date","")}</td>'
                     f'<td>{r.get("emails_sent","")}</td><td>{r.get("emails_failed","")}</td>'
                     f'<td>{badge}</td></tr>')
    if not log_rows:
        log_rows = '<tr><td colspan="5" style="color:var(--muted)">لا توجد بيانات</td></tr>'

    perf_rows = ""
    for r in d["perf_rows"]:
        perf_rows += (f'<tr><td>{r.get("timestamp","")}</td><td>{r.get("file","")}</td>'
                      f'<td>{r.get("rows","")}</td><td>{r.get("sec_الإجمالي","") or ""}</td></tr>')
    if not perf_rows:
        perf_rows = '<tr><td colspan="4" style="color:var(--muted)">لا توجد قياسات — شغّل: python main.py perf bench --file &lt;ملف&gt;</td></tr>'

    newest_file = "—"
    file_count = len(d["files"])
    if d["files"]:
        newest_file = f"{d['files'][0]['name']} (قبل {d['files'][0]['age_days']} يوم)"

    html = _DASHBOARD_HTML
    html = html.replace("{now}", d["now"])
    html = html.replace("{log_kpi}", log_kpi)
    html = html.replace("{file_count}", str(file_count))
    html = html.replace("{newest_file}", newest_file)
    html = html.replace("{perf_count}", str(len(d["perf_rows"])))
    html = html.replace("{checks_rows}", checks_rows)
    html = html.replace("{log_rows}", log_rows)
    html = html.replace("{perf_rows}", perf_rows)
    return html


def _run_server(port: int = 8080) -> int:
    try:
        from flask import Flask
    except ImportError:
        print("❌ مكتبة flask غير مثبتة. قم بتثبيتها: pip install flask")
        return 1

    app = Flask(__name__)

    @app.route("/")
    def _index():
        from flask import Response
        return Response(_render_dashboard(), mimetype="text/html")

    print("=" * 60)
    print(f"لوحة تحليل الأداء — افتح المتصفح على: http://localhost:{port}")
    print("لإيقاف الخادم اضغط Ctrl+C")
    print("=" * 60)
    app.run(host="127.0.0.1", port=port, debug=False)
    return 0

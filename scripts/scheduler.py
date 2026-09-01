import subprocess
from pathlib import Path

from .config_loader import BASE_DIR, load_config

BAT = BASE_DIR / "run_daily.bat"


def install() -> None:
    cfg = load_config()
    scfg = cfg["scheduler"]
    task = scfg["task_name"]
    time_str = scfg["time"]
    # أيام العمل فقط (الأحد-الخميس). السابق كان /SC DAILY فيُطلَق الجمعة والسبت
    # ثم يتجاهله السكربت — تشغيل بلا داعٍ يلوّث السجل.
    days = scfg.get("days", "SUN,MON,TUE,WED,THU")
    if not BAT.exists():
        print(f"ملف التشغيل غير موجود: {BAT}")
        return

    # بدون /RU تنشأ المهمة "تفاعلية" — أي لا تعمل إلا إذا كان المستخدم مسجّل الدخول.
    # هذا سبب شائع لتوقف الإرسال: الجهاز مقفول أو المستخدم غير مسجّل الساعة المحددة.
    run_as = str(scfg.get("run_as_user", "")).strip()
    identity = f'/RU "{run_as}" /IT ' if run_as else ""

    cmd = (
        f'schtasks /Create /F /TN "{task}" '
        f'/TR "{BAT}" /SC WEEKLY /D {days} /ST {time_str} {identity}'
    ).rstrip()

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if result.returncode == 0:
        print(f"تمت الجدولة أيام ({days}) الساعة {time_str} (اسم المهمة: {task}).")
        if not run_as:
            print(
                "تنبيه: لم يُحدَّد run_as_user في config.json، لذا المهمة تعمل فقط أثناء "
                "تسجيل دخول المستخدم الحالي. للتشغيل حتى مع قفل الجهاز، اضبط "
                'scheduler.run_as_user على "DOMAIN\\user" وأعد التثبيت.'
            )
    else:
        print("تعذر إنشاء المهمة — جرّب تشغيل الطرفية كمسؤول.")


def uninstall() -> None:
    cfg = load_config()
    task = cfg["scheduler"]["task_name"]
    result = subprocess.run(f'schtasks /Delete /F /TN "{task}"', shell=True, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode == 0:
        print(f"تم حذف المهمة: {task}.")
    else:
        print(result.stderr.strip())


def status() -> None:
    cfg = load_config()
    task = cfg["scheduler"]["task_name"]
    # /V /FO LIST يعرض "آخر وقت تشغيل" و"آخر نتيجة" — وهما المعلومتان اللتان
    # تكشفان هل توقفت المهمة فعلاً وبأي رمز خروج.
    result = subprocess.run(
        f'schtasks /Query /TN "{task}" /V /FO LIST',
        shell=True, capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())

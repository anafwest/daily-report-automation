import subprocess
from pathlib import Path

from .config_loader import BASE_DIR, load_config

BAT = BASE_DIR / "run_daily.bat"


def install() -> None:
    cfg = load_config()
    scfg = cfg["scheduler"]
    task = scfg["task_name"]
    time_str = scfg["time"]
    if not BAT.exists():
        print(f"ملف التشغيل غير موجود: {BAT}")
        return
    cmd = (
        f'schtasks /Create /F /TN "{task}" '
        f'/TR "{BAT}" /SC DAILY /ST {time_str}'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if result.returncode == 0:
        print(f"تمت الجدولة يومياً الساعة {time_str} (اسم المهمة: {task}).")
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
    result = subprocess.run(f'schtasks /Query /TN "{task}"', shell=True, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())

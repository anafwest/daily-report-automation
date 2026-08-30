@echo off
chcp 65001 >nul
cd /d "%~dp0"
"C:\Users\Malfahd\AppData\Local\Programs\Git\cmd\git.exe" pull --rebase origin main
"C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe" -u main.py run_daily --headless >> "output\run_daily.log" 2>&1

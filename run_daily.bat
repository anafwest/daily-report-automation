@echo off
chcp 65001 >nul
cd /d "%~dp0"
"C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe" -u main.py run_daily >> "output\run_daily.log" 2>&1

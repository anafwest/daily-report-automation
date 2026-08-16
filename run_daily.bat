@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u main.py run_daily >> "output\run_daily.log" 2>&1

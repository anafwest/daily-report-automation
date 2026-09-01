@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ============================================================
rem  Daily scheduled run - Riyadh daily request report
rem ============================================================

rem FIX: the log redirect below fails (and the whole run silently does nothing)
rem if the output folder is missing. output/ is gitignored, so a fresh clone
rem or a cleanup leaves it absent.
if not exist "output" mkdir "output"
set "LOGFILE=output\run_daily.log"

echo ============================================================ >> "%LOGFILE%"
echo [%DATE% %TIME%] scheduled run started >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

rem Resolve git (hardcoded path kept for the original machine, with fallback)
set "GIT_EXE=C:\Users\Malfahd\AppData\Local\Programs\Git\cmd\git.exe"
if not exist "%GIT_EXE%" set "GIT_EXE=git"
echo [%DATE% %TIME%] git pull >> "%LOGFILE%"
"%GIT_EXE%" pull --rebase origin main >> "%LOGFILE%" 2>&1

rem Resolve python (hardcoded path kept for the original machine, with fallback)
set "PY_EXE=C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

echo [%DATE% %TIME%] using python: %PY_EXE% >> "%LOGFILE%"
"%PY_EXE%" -u main.py run_daily --headless >> "%LOGFILE%" 2>&1
set "RC=%ERRORLEVEL%"

echo [%DATE% %TIME%] finished, exit code: %RC% >> "%LOGFILE%"
exit /b %RC%

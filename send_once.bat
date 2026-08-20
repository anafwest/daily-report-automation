@echo off
chcp 65001 >nul
cd /d "%~dp0"
title إرسال لمرة واحدة - جميع الإدارات

echo.
echo ================================================================
echo   إرسال لمرة واحدة فقط - جميع الإدارات (إرسال فعلي)
echo ================================================================
echo.

REM 1) تحديث الكود من GitHub
echo [1/6] تحديث الكود من GitHub...
git pull --ff-only >nul 2>nul
if %errorlevel%==0 (echo     تم التحديث) else (echo     تنبيه: تعذر التحديث - نكمل بالكود الموجود)

REM 2) تحديد Python
set PYTHON_EXE=python
if exist "C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe" set PYTHON_EXE=C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe

REM 3) فحص وضع الإرسال (test_mode)
echo [2/6] فحص وضع الإرسال...
set TM=
powershell -NoProfile -Command "$c=Get-Content config.json -Raw|ConvertFrom-Json; if($c.test_mode.enabled -eq $true){'ON'}else{'OFF'}" > %TEMP%\tm.txt 2>nul
if exist %TEMP%\tm.txt set /p TM=<%TEMP%\tm.txt
if "%TM%"=="ON" (
    echo     ⚠️  وضع الاختبار ما زال مفعّلاً - الرسائل ستذهب إلى anaf@alriyadh.gov.sa فقط
    echo     للإرسال لجميع الإدارات: افتح config.json واجعل test_mode.enabled = false
    pause
    exit /b 1
)
echo     ✅ وضع الإرسال الفعلي - الرسائل ستذهب لجميع الإدارات

REM 4) معاينة المستلمين (بدون إرسال)
echo [3/6] معاينة المستلمين (بدون إرسال)...
"%PYTHON_EXE%" -u main.py run_daily --dry-run
echo.
echo     ↑ راجع القائمة أعلاه: هذه هي الجهات التي ستستلم الرسائل.

REM 5) تأكيد الإرسال
echo [4/6] تأكيد الإرسال
set /p CONFIRM=اكتب نعم (أو y) للإرسال الفعلي لجميع الإدارات، أو أي حرف للإلغاء: 
if /i not "%CONFIRM%"=="y" if not "%CONFIRM%"=="نعم" (
    echo تم الإلغاء.
    pause
    exit /b 1
)

REM 6) الإرسال الفعلي
echo [5/6] جارٍ الإرسال الفعلي لجميع الإدارات...
"%PYTHON_EXE%" -u main.py run_daily > output\send_all_once.log 2>&1
echo     تم - السجل الكامل في output\send_all_once.log
echo.
echo ================================================================
type output\send_all_once.log
echo ================================================================

REM 7) فحص وجود مهمة مجدولة (لضمان مرة واحدة فقط)
echo [6/6] فحص المهمة المجدولة...
schtasks /query /tn "AutomationDailyReport" >nul 2>&1
if %errorlevel%==0 (
    echo     ⚠️  يوجد مهمة مجدولة (AutomationDailyReport) ستشغّل الأداة يومياً!
    echo     لضمان مرة واحدة فقط أزلها بالأمر:
    echo     python main.py schedule --action uninstall
) else (
    echo     ✅ لا توجد مهمة مجدولة - لن تتكرر تلقائياً
)
echo.
pause

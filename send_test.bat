@echo off
chcp 65001 >nul
cd /d "%~dp0"
title إرسال تجريبي - anaf@alriyadh.gov.sa
echo.
echo ================================================================
echo   إرسال تجريبي - كل الرسائل إلى anaf@alriyadh.gov.sa فقط
echo ================================================================
echo.

REM 1) تحديث الكود من GitHub (إن أمكن - لا نتوقف عند الفشل)
echo [1/5] تحديث الكود من GitHub...
git pull --ff-only >nul 2>nul
if %errorlevel%==0 (echo     تم التحديث) else (echo     لا يوجد اتصال أو لا جديد - نكمل بالكود الموجود)

REM 2) تحديد Python
set PYTHON_EXE=python
if exist "C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe" set PYTHON_EXE=C:\Users\Malfahd\AppData\Local\Python\pythoncore-3.14-64\python.exe
echo [2/5] بايثون: %PYTHON_EXE%

REM 3) فحص أمان: وضع الاختبار يجب أن يكون مفعلاً قبل أي إرسال
set TM=
powershell -NoProfile -Command "$c=Get-Content config.json -Raw|ConvertFrom-Json; if($c.test_mode.enabled -eq $true){'ON'}else{'OFF'}" > %TEMP%\tm.txt 2>nul
if exist %TEMP%\tm.txt set /p TM=<%TEMP%\tm.txt
if not "%TM%"=="ON" (
    echo.
    echo  ⚠️  تنبيه: وضع الاختبار غير مفعّل في config.json!
    echo      الرسائل ستذهب للإدارات الفعلية - لن نكمل.
    echo      فعّل test_mode.enabled = true ثم أعد المحاولة.
    pause
    exit /b 1
)
echo [3/5] وضع الاختبار مفعّل - كل الرسائل إلى anaf@alriyadh.gov.sa

REM 4) المكتبات
echo [4/5] التأكد من المكتبات...
"%PYTHON_EXE%" -m pip install -r requirements.txt -q 2>nul

REM 5) التنفيذ
if not exist output mkdir output
echo [5/5] جارٍ تشغيل الدورة اليومية (إرسال تجريبي)...
"%PYTHON_EXE%" -u main.py run_daily > output\send_test.log 2>&1
echo.
echo ================================================================
type output\send_test.log
echo ================================================================
echo.
echo  ✅ انتهى - افتح الآن بريد anaf@alriyadh.gov.sa وتأكد من الرسائل.
pause

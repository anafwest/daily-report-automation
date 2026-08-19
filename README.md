# نظام الأتمتة الذكية للتقارير والتوزيع اليومي

نظام يعمل يومياً (خارج أوقات الدوام عبر الجدولة) يقوم بدورة كاملة:
**الدخول للبوابة الموحدة ← استخراج التقرير الشامل ← فحص التقرير ← المعالجة والتوحيد ← تقسيم الطلبات حسب الإدارات ← إرسال ملف لكل إدارة ← تسجيل كل عملية ← إرسال تقرير يومي للمسؤول.**

## مراحل النظام

```
1. الدخول (SSO + تحقق ثنائي) → 2. التقاط التقرير → 3. فحص التقرير → 4. التقسيم حسب الإدارة
→ 5. الإرسال → 6. سجل التشغيل → 7. التقرير اليومي للمسؤول
```

## متطلبات أول مرة

1. تثبيت المكتبات:
   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
   (النظام يستخدم متصفح Chrome بملف تعريف دائم.)

2. تعبئة ملف `.env`:
   ```
   SSO_USERNAME=الرقم_الوظيفي
   SSO_PASSWORD=كلمة_المرور
   SMTP_SENDER=بريد_المرسل@...gov.sa
   SMTP_PASSWORD=كلمة_المرور_أو_App_Password
   OTP_IMAP_EMAIL=البريد_الذي_يستقبل_الرمز
   OTP_IMAP_PASSWORD=كلمة_مرور_هذا_البريد
   ```

3. تجهيز ملف `email_list.xlsx` (جدول الإعدادات القابل للتعديل) بالأعمدة:
   - `الإدارة` — الاسم الموحد للإدارة
   - `البريد الإلكتروني` — بريد الإدارة
   - `CC` — بريد نسخة إضافية (اختياري، تُفصل بـ `;`)
   - `حالة الإرسال` — `فعال` / `معطل`

   مثال:
   | الإدارة | البريد الإلكتروني | CC | حالة الإرسال |
   |---|---|---|---|
   | إدارة رخص البناء - غرب | West.BL@alriyadh.gov.sa | | فعال |
   | إدارة المساحة | SURV@alriyadh.gov.sa | manager@alriyadh.gov.sa | فعال |

## الأوامر

### الدخول (تلقائي بالكامل — كابتشا OCR + رمز التحقق)
```
python main.py login
```
- قراءة رمز التحقق تتم من **أحدث بريد OTP فقط** (لقطة للرموز قبل الدخول وانتظار الرمز الجديد الذي يصل خلال 30-50 ثانية).
- للدخول اليدوي: `python main.py login --manual`

### التقاط التقرير من البوابة
```
python main.py capture --url <رابط_التقرير>
python main.py capture --export --url <رابط_التقرير>
```

### التقاط التقرير من علاقات العملاء (CRM)
```
python main.py capture --crm
```
التدفق: دخول ADFS ← قسم "الطلبات" ← اختيار العرض (`view_name` في `config.json`، وبديله "تقرير كافة الطلبات") ← تصدير إلى Excel ← تحميل `output/تقرير_التاريخ.xlsx`.
- بيانات الدخول: `CRM_USERNAME` (بصيغة البريد) و `CRM_PASSWORD` في `.env`.
- الإعدادات: قسم `report.crm` في `config.json` (`view_name`, `fallback_view_name`, `download_timeout_sec`).
- **شرط أساسي**: الوصول إلى `crm.alriyadh.gov.sa` يكون من **شبكة الشركة** فقط (اسم داخلي لا يُقدَّم عبر الإنترنت).
- يُستدعى تلقائياً في الدورة اليومية عند عدم تمرير `--source`.

### الدورة اليومية الكاملة
```
python main.py run_daily --source output/بيانات_خام.xlsx --dry-run   (معاينة)
python main.py run_daily --source output/بيانات_خام.xlsx             (إرسال فعلي)
```
إذا لم يُمرر `--source` يُبحث عن أحدث ملف xlsx في `output/`.

### دورة تجريبية على بيانات عينة (test-send)
أمر يولّد ملف تقرير تجريبي (بإدارات حقيقية من جدول الإعدادات + حالات ومناطق متنوعة) ويمر على الدورة كاملة: فحص ← فلاتر ← تقسيم ← معاينة الرسائل، **بدون إرسال أي بريد**:
```
python main.py test-send                (معاينة في الطرفية)
python main.py test-send --eml          (+ حفظ نسخ .eml في output/معاينة_الإيميلات/ لفتحها في Outlook)
```

### قفل الاختبار (test_mode) — الأهم أثناء التعديلات
طالما `test_mode.enabled = true` في `config.json`، **كل** الرسائل (حتى بدون أي خيار إضافي) تتحول إلى `force_recipient` فقط مع وسم `[تجربة]` — لا يصل أي بريد لأي إدارة أخرى مهما حدث.
```json
"test_mode": { "enabled": true, "force_recipient": "anaf@alriyadh.gov.sa", "subject_prefix": "[تجربة] " }
```
عند الانتهاء من التعديلات: غيّر `enabled` إلى `false` ليعود الإرسال الطبيعي للإدارات.

### إرسال تجريبي حقيقي (test-to)
تحويل **كل** الرسائل إلى بريد واحد محدد مع وسم `[تجربة]` في الموضوع وبيان المستلم الأصلي — آمن تمامًا ولا يصل أي بريد للإدارات:
```
python main.py run_daily --source output/بيانات_خام.xlsx --test-to بريدك@الجهة.gov.sa
python main.py send --source output/بيانات_خام.xlsx --test-to بريدك@الجهة.gov.sa
```

### فحص تقرير فقط
```
python -c "from scripts.validate_report import validate_report; print(validate_report('output/بيانات_خام.xlsx'))"
```

### الجدولة اليومية (Task Scheduler)
```
python main.py schedule --action install     (مهمة يومية بالوقت في config.json)
python main.py schedule --action uninstall
python main.py schedule-status
```
عدّل الوقت في `config.json` → `scheduler.time`.

### تقرير الإدارات والبريد
```
python main.py report               (عرض في الطرفية)
python main.py report --xlsx         (حفظ كملف Excel)
python main.py report --send         (إرسال إلى anaf@alriyadh.gov.sa مع معاينة)
python main.py report --send --dry-run   (معاينة بدون إرسال)
```

## قواعد المطابقة والأمان (الأهم)

- **فلترة حالة الطلب**: يتم سحب الطلبات فقط بحالة `قيد الإجراء` أو `جاري العمل` من عمود "حالة الطلب" في التقرير (يتعرّف تلقائيًا أيضًا على "الحالة الفرعية" أو "الحالة" إذا كان الاسم مختلفًا).
- **فلترة المنطقة (الغرب فقط)**: يتم الاحتفاظ فقط بالطلبات التي تحتوي كلمة "غرب" في عمود "الإدارة - الوكالة الأساسية للطلب" (تُستبعد الطلبات التابعة للجنوب والوسط والشرق والشمال). يمكن تعديل العمود والكلمات من `config.json` ← `report.region_filter`.
- **مطابقة مؤكدة → إرسال** / **مطابقة غير مؤكدة → إيقاف وإشعار**.
- الاسم يُوحَّد أولاً (مسافات، شرطات، أقواس، اختلاف الاتجاه) ثم يُطابق بدقة ضد جدول الإعدادات.
- أي إدارة غير موجودة في الجدول → ملف يُنشأ لكن **لا يُرسل** ويُعلَّم "إدارة جديدة تحتاج اعتماد".
- إدارة بلا بريد أو حالة معطلة → ملف يُنشأ لكن لا يُرسل.
- طلبات بلا إدارة → `output/Unassigned.xlsx` ولا تُرسل.
- التقرير يُفحص قبل المعالجة: وجود الملف، تاريخ اليوم، الأعمدة المطلوبة، عدم الفراغ، وحد الـ 100,000 سجل (إذا بلغه الملف يُعتبر مشكوكاً في اقتطاعه ولا يُعتمد).

## المخرجات

| الملف | المحتوى |
|---|---|
| `output/مقسمة/` | ملف لكل إدارة |
| `output/Unassigned.xlsx` | طلبات بلا إدارة |
| `output/إدارات_جديدة.xlsx` | إدارات تحتاج اعتماد التوزيع |
| `output/إدارات_بدون_بريد.xlsx` | إدارات بلا بريد معتمد |
| `output/ملخص_الإدارات.xlsx` | ملخص الإدارات وعدد الطلبات |
| `output/ملخص_الإرسال.xlsx` | سجل كل إرسال/فشل/حظر |
| `output/سجل_التشغيل.csv` | سجل مركزي برقم Run ID |
| `output/تقرير_التشغيل_اليومي.xlsx` | تقرير المسؤول (🟢/🟡/🔴) |

## ملاحظات

- الإرسال الفعلي يتم عبر جلسة OWA (`send_via: owa`) داخل المتصفح الدائم للجلسة.
- لا تُشارك ملف `.env` أو `.browser_profile/`.
- لا تُخزَّن رموز OTP في السجلات.

## النقل إلى جهاز المدير

1. نسخ مجلد المشروع بالكامل (بما فيه `.env` و `.browser_profile/` و `email_list.xlsx` الحقيقي).
2. تثبيت المكتبات على الجهاز الجديد:
   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
3. في `config.json`:
   - تأكد أن `report.crm.view_name` = **"التقرير الشامل"** (متاح في حساب المدير).
   - اضبط `email_list.file` على ملف الإدارات الرسمي.
4. على الجهاز الجديد (متصل بشبكة الشركة):
   ```
   python main.py login            (مرة واحدة، وتأكد من الوصول لعلاقات العملاء)
   python main.py capture --crm    (اختبار الالتقاط ثم تحقق من output/تقرير_التاريخ.xlsx)
   python main.py run_daily --dry-run
   python main.py run_daily
   python main.py schedule --action install
   ```
5. إشعار تقرير المسؤول: اضبط `admin_report.to` في `config.json`.

### تشغيل تجريبي لمرة واحدة عبر GitHub Actions (مؤقت)
الملف `.github/workflows/test-send.yml` يعمل على **Runner محلي مثبت على جهاز الشركة** (`runs-on: self-hosted`) — ضروري لأن خادم البريد لا يُتاح إلا من شبكة الشركة.

**التشغيل:**
1. جهّز الـ runner على جهاز الشركة: `Settings ← Actions ← Runners ← New self-hosted runner` واتبع الأوامر (Windows x64)، ثم شغّل `run.cmd` واتركه مفتوحًا.
2. من تبويب **Actions** اختر ورك فلو `test-send` ثم **Run workflow** (خانة `project_dir` تُملأ فقط إذا لم يُكتشف المجلد تلقائيًا).
3. افحص بريد `anaf@alriyadh.gov.sa` — طالما `test_mode.enabled = true` في `config.json` لا يصل أي بريد للإدارات.

**الحذف بعد الانتهاء:**
- احذف الملف `.github/workflows/test-send.yml` من المستودع (git rm ثم push).
- أزل الـ runner من الجهاز: `cd C:\actions-runner` ثم `.\config.cmd remove --token <رمز-جديد>` واحذف المجلد.

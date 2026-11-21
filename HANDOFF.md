# تحویل ادامهٔ کار ecom-project

آخرین به‌روزرسانی: 2026-11-21. ابتدا این فایل و سپس AGENTS.md، spec.md و acceptance.md را بخوانید. این سند وضعیت اجرایی است، نه قرارداد محصول جدید.

## محل و مسیر اجرا
- مخزن: `C:\Users\mhzarneshani\Downloads\ecom-postgres-starter-v2\ecom-project`
- شاخهٔ این مرحله: `codex/launcher-cleanup-handoff`؛ ادامهٔ شاخهٔ `stabilization/operator-review-import`.
- تنها راه‌انداز رسمی در ریشه: `Start-Windows.cmd`؛ HTML/JS و API در یک سرور `web_app.py` روی loopback:8765.
- `Start-Windows.cmd --setup` مسیر صریح نصب/پیکربندی PostgreSQL است. دو CMD داخلی در scripts/windows وابستگی راه‌انداز هستند، نه برنامه‌های مستقل.
- `--help` و `--credential-status` بدون راه‌اندازی/مهاجرت پایگاه اجرا می‌شوند؛ بررسی وابستگی Python همچنان انجام می‌شود.

## معماری و قابلیت‌های حفظ‌شده
`domain.py`: قواعد و محاسبات؛ `readers.py`: خوانندهٔ اکسل و ورودی نرمال؛ `store.py`: PostgreSQL، revision/conflict، گزارش و ثبت دستی؛ `triage.py`: چرخهٔ پرونده/شواهد/تصمیم؛ `web_app.py`: HTTP، session و مجوز؛ `frontend/`: UI فارسی RTL؛ `web_ai.py` و `web_config.py`: Provider، تنظیمات و خطاها؛ `live_test_ledger.py`: رزرو پایدار درخواست/هزینه و بازبینی؛ `db_migrations.py` و `migrations/`: نسخه‌بندی schema.

برنامهٔ جدید، پایگاه جایگزین یا فرمول فروش جدید ساخته نشده است. فایل‌های قدیمی Streamlit و transport هنوز وابستگی تست/سازگاری دارند؛ بدون بررسی حذف نشوند. Universal AI Kit خارج از محدوده است.

## کارهای انجام‌شده
1. جداسازی موفقیت شبکه، احراز هویت، inference و Mock؛ کنترل مقصد Provider و خطاها؛ محدودیت نهایی خروجی controlled test برابر 150؛ عدم جایگزینی پنهان Provider/model/key.
2. Migrationهای 001 تا 003 با checksum، حفظ داده و rollback محافظت‌شده؛ رزرو درخواست پیش از ارسال، قفل همزمانی و حفظ نتیجهٔ نامشخص پس از توقف؛ ثبت هویت/زمان اصلاح دستی.
3. بازبینی مدیر سیستم برای تلاش AI متوقف‌شده با ثبت append-only؛ بازبینی انسانی موفقیت Provider نیست و شمارنده/هزینه را بازنشانی نمی‌کند.
4. ورود XLSX قالب موجود با سقف حجم/ساختار، پیش‌نمایش آمار و نمونه، خطای سطری، تأیید nonce یک‌بارمصرف با انقضای ده دقیقه، تشخیص تغییر داده بین پیش‌نمایش و ثبت، ثبت trace و actor سرور. XLS قدیمی و نگاشت آزاد ستون‌ها پشتیبانی نشده‌اند.
5. رفع و تست رگرسیون TCP reset ویندوز هنگام رد upload غیرمجاز؛ پاسخ 403 خوانا می‌ماند.
6. پاک‌سازی CMD: چهار wrapper قدیمی Start-DeepSeek، Check-GapGPT، Test-AvalAI-Model و Test-GapGPT حذف شدند؛ دو helper به scripts/windows منتقل شدند. کد Python ابزارها و تست‌ها حفظ شدند. میان‌بر شخصی قدیمی باید به Start-Windows تغییر کند. Git مسیر بازیابی wrapperهاست.
7. تست CMD واقعی از cwd متفاوت و پروفایل موقت خالی؛ help و credential-status نباید provisioning انجام دهند. راهنمای Windows و پیام خطای startup اصلاح شدند.

## شواهد آزمون
- مرحلهٔ قبل: 169 تست موفق در 134.69 ثانیه؛ reports/workflow-final.log.
- این مرحله، متمرکز: 3 تست موفق در 16.02 ثانیه؛ reports/launcher-cleanup-focused.log.
- نتیجهٔ مجموعهٔ کامل این مرحله: **171 passed in 136.94s**؛ reports/launcher-cleanup-final.log؛ PostgreSQL موقت خاموش شد. `git diff --check` نیز PASS است.
- فرمان کامل: `.venv\Scripts\python.exe qa/run_tests.py -- -q`.
- تست‌ها PostgreSQL موقت مجزا می‌سازند و socket غیرمحلی/کلیدهای واقعی را از محیط تست کنار می‌گذارند. دیتابیس عملیاتی را به ECOM_TEST_DSN معرفی نکنید.
- آخرین بازیابی موفق backup: workshop-20261121T061550Z.dump در `%LOCALAPPDATA%\ActiveEcomBootcamp\backups`؛ در cluster موقت records=2393، conflicts=0، cases=2، triage_state=2، model_budget=2. این شمارش، اندازهٔ دادهٔ عملیاتی در زمان backup است، نه اثبات صحت همهٔ رکوردها.
- migration عملیاتی، double-click تعاملی، تطابق بصری جدید و Live AI: NOT RUN. HTTP/Mock را معادل این موارد اعلام نکنید.

## محدودیت قطعی Live
درخواست بعدی کاربر در فایل پیوست، تماس با AvalAI/GapGPT را ممنوع کرده است. ادامهٔ کار صرفاً آفلاین است. هیچ دستور probe یا diagnostics شبکه‌ای اجرا نکنید. کلید ارسالی در چت استفاده نشده و نباید استفاده شود.
در مراحل اخیر هر Provider صفر درخواست واقعی داشته است؛ مصرف و صورتحساب تأییدشده NOT RUN است. آخرین بررسی محیط قبلی هر دو کلید را MISSING گزارش کرده بود؛ این وضعیت تاریخی است، برای نشست جدید فقط SET/MISSING را بررسی کنید و مقدار را چاپ نکنید.
برای بازشدن gate در آینده: دستور صریح جدید اپراتور، هر دو credential امن، مدل و قیمت حساب معتبر، سقف قابل‌اعمال 0.20 دلار/Provider، حداکثر 6 درخواست شامل خطا/discovery، حداکثر150 خروجی و فقط متن مصنوعی لازم است. deepseek-chat مدل درخواستی AvalAI است ولی دسترسی حساب اثبات نشده؛ مدل دقیق GapGPT و ارزان‌ترین انتخاب مناسب تأیید نشده است. هیچ retry خودکار برای نتیجهٔ هزینه‌دار نامشخص مجاز نیست.

## ترتیب کار باقی‌مانده
1. **قدم بعدی مشخص: آزمون مرورگر روی دیتابیس مجزا.** UI فعلی را با sales-agent-desk-ai-contextual.html در 1280/768/390 مقایسه کنید؛ upload/preview/confirm، خطا، keyboard/focus، پرونده و پنل AI را آزمایش کنید. فقط Mock صریح، بدون تماس Provider؛ نقص مشاهده‌شده را با تست رگرسیون اصلاح کنید. اسکرین‌شات‌های قدیمی اثبات نسخهٔ فعلی نیستند.
2. روی یک کپی بازیابی‌شده، ارتقای schema تا003 و حفظ داده را بررسی کنید؛ سپس با برنامهٔ rollout/backup وارد محیط واقعی شوید. آغاز عادی برنامه ممکن است migration را اعمال کند؛ برای تست UI از پایگاه عملیاتی استفاده نکنید.
3. scoped history برای observer، attribution تصمیم‌های پرونده و خروجی گزارش با تطابق ارقام/مجوزها را بررسی و کمبود واقعی را تکمیل کنید. قواعد جدید پرونده اختراع نشوند.
4. hosted logout/session، هویت پراکسی، rate limit و TLS را در محیط استقرار واقعی اثبات کنید؛ انتخاب role در حالت آموزشی احراز هویت production نیست.
5. اندازه‌گیری performance با دادهٔ نماینده و تکمیل Acceptance Matrix AC-01..30 با شواهد؛ فعلاً production-ready اعلام نشود.
6. پس از مجوز جدید و رفع gateهای بالا، Live را از تنظیمات و دستیار اصلی با متن مصنوعی آزمون کنید؛ موفقیت آفلاین جایگزین آن نیست.

## نگهداری مخزن و گزارش‌ها
Commitهای پیشین: 944d891 (persistence)، 39024c1 (گزارش)، a5a512d (review/import)، 12a14be (گزارش). برای commit همین مرحله `git log -3 --oneline` را ببینید.
فایل‌های untracked از قبل: `.streamlit/`، `reports/ui/`، `reports/unified/`؛ دست‌نخورده‌اند. `project-review.zip` آرشیو ignored قبلی است و حذف نشده. فایل‌های .log در Git نیستند؛ نتیجهٔ خلاصه داخل گزارش tracked ثبت شود.
گزارش‌های قدیمی با شمارش 139 یا155 شواهد تاریخی‌اند. مرجع جدید این فایل، ecom-operator-review-import.md و ecom-next-execution-plan.md است. مسیرهای CMD قدیمی در گزارش تاریخی را دستور اجرا تلقی نکنید.

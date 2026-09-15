# تطبيق الجوال

تطبيق Expo وReact Native للموظف، ويستخدم FastAPI نفسه الخاص بمنصة الويب. يتيح الدخول، واستعادة الجلسة من التخزين الآمن، وعرض الفواتير وتصفية حالاتها، وعرض تفاصيل الفاتورة والتنبيهات ودرجة المخاطر، ورفع PDF أو JPEG أو PNG أو UBL XML إلى مشروع مسموح.

## التشغيل على Android Emulator

1. شغّل PostgreSQL وFastAPI من جذر المشروع عبر `Start_Project.cmd`.
2. من هذا المجلد نفّذ `npm start`.
3. اضغط `a` لفتح Android Emulator. يستخدم التطبيق افتراضيًا `http://10.0.2.2:8000/api/v1` للوصول إلى الخادم على Windows.

## التشغيل على هاتف داخل الشبكة المحلية

أنشئ ملف `.env.local` في هذا المجلد واكتب عنوان IPv4 الخاص بجهاز Windows، مثل:

```dotenv
EXPO_PUBLIC_API_URL=http://192.168.1.20:8000/api/v1
```

أضف IPv4 نفسه إلى `TRUSTED_HOSTS` في ملف `.env` بجذر المشروع، وأوقف المشروع ثم شغّل الخدمات مع إتاحة API للشبكة:

```powershell
Set-Location 'C:\path\to\Graduation-Project'
& '.\10_Deployment\Scripts\stop-local.ps1'
& '.\10_Deployment\Scripts\start-local.ps1' -ApiHost 0.0.0.0
```

قد يطلب Windows السماح للمنفذ 8000 في الشبكة الخاصة. لا تحفظ عنوانًا أو كلمة مرور خاصة داخل Git، واستخدم HTTPS قبل أي تجربة خارج شبكة تطوير موثوقة.

## التحقق

- `npm run typecheck` للتحقق من TypeScript.
- `npm run format:check` للتحقق من تنسيق الملفات.
- `npm run build:android-bundle` لبناء حزمة JavaScript وملفات Expo الخاصة بمنصة Android.
- `npx expo-doctor` لفحص توافق حزم Expo.

ملفات Android وiOS الأصلية لا تحفظ في المستودع؛ يولدها Expo عند الحاجة. بناء APK/AAB موقع للمتجر يحتاج حساب Expo/EAS وبيانات توقيع، وهو جزء من مرحلة النشر.

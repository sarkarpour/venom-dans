# FerroWidget for Android / راهنمای نصب و اجرای اندروید

[English](#english) | [فارسی](#فارسی)

---

## English

FerroWidget on Android can be run in two ways:

### Method 1: Web App / Progressive Web App (PWA) - Recommended
A lightweight, hardware-accelerated WebGL 2.0 version with live microphone reactivity, multi-touch fluid interaction, and all 4 themes.
1. Open `packaging/android/web_visualizer/index.html` in Chrome or mobile browser, or host it locally/online.
2. In Chrome on Android, tap the three dots **(⋮)** and select **"Add to Home screen"** or **"Install App"**.
3. It installs directly as a native standalone app with full offline support.
4. Tap **🎤 Mic** to let the fluid dance to ambient music or speech.

### Method 2: Convert to Standalone Android APK
To create a native `.apk` from the WebGL visualizer:
```bash
npm install -g @pwabuilder/pwabuilder
# or use Capacitor:
npm install @capacitor/core @capacitor/cli @capacitor/android
npx cap init FerroWidget com.ferrowidget.app --web-dir packaging/android/web_visualizer
npx cap add android
npx cap build android
```

### Method 3: Native Linux Container via Termux + Termux:X11
To run the full Python desktop version on rooted or non-rooted Android:
1. Install **Termux** and **Termux:X11** from F-Droid.
2. In Termux, run:
```bash
curl -sSL https://raw.githubusercontent.com/asa/ferrowidget/main/packaging/android/termux_install.sh | bash
```
3. Open Termux:X11 and run `~/start_ferrowidget.sh`.

---

## فارسی

<div dir="rtl">

فرومگنت روی اندروید به دو روش قابل استفاده است:

### روش ۱: اپلیکیشن تحت وب پیش‌رونده (PWA) - پیشنهاد شده
یک نسخه فوق‌العاده سبک، روان و مبتنی بر WebGL 2.0 با قابلیت اتصال به میکروفون، واکنش به موسیقی و لمس چندگانه:
۱. فایل `packaging/android/web_visualizer/index.html` را در مرورگر کروم گوشی باز کنید (یا روی وب‌سرور قرار دهید).  
۲. در منوی کروم (سه نقطه بالا سمت راست) گزینه **«Add to Home screen»** یا **«نصب برنامه (Install)»** را انتخاب کنید.  
۳. این برنامه مانند یک نرم‌افزار نیتیو با آیکون اختصاصی روی صفحه گوشی شما نصب می‌شود و حتی بدون اینترنت (آفلاین) کار می‌کند.  
۴. با زدن دکمه **🎤 Mic** دسترسی میکروفون را بدهید تا قطرات فروسیال با آهنگ‌های اطراف شما برقصند.

### روش ۲: ساخت فایل نصبی APK اندروید
برای کامپایل نسخه وب به فایل `.apk`:
می‌توانید با استفاده از ابزار رایگان [PWABuilder](https://www.pwabuilder.com/) یا فریمورک Capacitor، در کمتر از ۵ دقیقه خروجی APK امضا شده برای نصب مستقیم روی هر گوشی اندرویدی بگیرید.

### روش ۳: اجرای محیط کامل لینوکسی با Termux و Termux:X11
برای اجرای نسخه کامل پایتونی روی گوشی:
۱. برنامه‌های **Termux** و **Termux:X11** را از F-Droid نصب کنید.  
۲. اسکریپت `packaging/android/termux_install.sh` را اجرا کنید.  
۳. برنامه Termux:X11 را باز کنید تا فروسیال با فیزیک و رندرر کامل پایتون به صورت ویجت اجرا شود.

</div>

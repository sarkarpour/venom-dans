# FerroWidget for Android / راهنمای نصب و اجرای اندروید

[English](#english) | [فارسی](#فارسی)

---

## English

FerroWidget on Android can be run in two ways:

### Method 1: Web App / Progressive Web App (PWA) - Recommended
A lightweight, hardware-accelerated WebGL 2.0 version with:
- Full desktop parity: 64 droplets, 19 electromagnets, underdamped spring ODEs, and Rosensweig hexagonal spikes.
- **🎵 Select Song (انتخاب آهنگ)**: Directly pick and play any music file (MP3, WAV, FLAC, OGG, M4A) right inside the visualizer without requiring any microphone or device permissions.
- **🎤 Microphone Input**: Reacts dynamically to ambient speech or music with smart permission error handling.
- **🎶 Built-in Synth Demo**: Instant test beat.
1. Open `packaging/android/web_visualizer/index.html` in Chrome or mobile browser, or host it locally/online.
2. In Chrome on Android, tap the three dots **(⋮)** and select **"Add to Home screen"** or **"Install App"**.
3. It installs directly as a native standalone app with full offline support.
4. Tap **🎵 انتخاب آهنگ** to pick your music file and play it right there, or tap **🎤 Mic** for live ambient audio.

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
curl -sSL https://raw.githubusercontent.com/sarkarpour/venom-dans/main/packaging/android/termux_install.sh | bash
```
3. Open Termux:X11 and run `~/start_ferrowidget.sh`.

---

## فارسی

<div dir="rtl">

فرومگنت روی اندروید به دو روش قابل استفاده است:

### روش ۱: اپلیکیشن تحت وب پیش‌رونده (PWA) - پیشنهاد شده
یک نسخه فوق‌العاده سبک، روان و مبتنی بر WebGL 2.0 با برابری کامل با نسخه لینوکس:
- فیزیک کامل ۶۴ قطره، ۱۹ آهنربای الکتریکی، نوسانات فنری میرا و خارهای شش‌ضلعی روزنزویگ.
- **🎵 انتخاب مستقیم آهنگ (بدون نیاز به دسترسی)**: با زدن دکمه «🎵 انتخاب آهنگ» هر فایل صوتی (MP3، WAV، FLAC و...) را مستقیماً از گوشی انتخاب کنید تا با کیفیت بالا همزمان پخش شده و قطرات با آن برقصند.
- **🎤 ورودی میکروفون**: با مدیریت هوشمند دسترسی‌ها و راهنمای حالت آفلاین.
- **🎶 تست دمو**: پخش ریتم الکترونیک جهت مشاهده سریع رقص مایع.
۱. فایل `packaging/android/web_visualizer/index.html` را در مرورگر کروم گوشی باز کنید (یا روی وب‌سرور قرار دهید).  
۲. در منوی کروم (سه نقطه بالا سمت راست) گزینه **«Add to Home screen»** یا **«نصب برنامه (Install)»** را انتخاب کنید.  
۳. این برنامه مانند یک نرم‌افزار نیتیو با آیکون اختصاصی روی صفحه گوشی شما نصب می‌شود و حتی بدون اینترنت (آفلاین) کار می‌کند.  
۴. با زدن دکمه **🎵 انتخاب آهنگ** فایل موزیک خود را پخش کنید، یا با دکمه **🎤 میکروفون** به صدای محیط گوش دهید.

### روش ۲: ساخت فایل نصبی APK اندروید
برای کامپایل نسخه وب به فایل `.apk`:
می‌توانید با استفاده از ابزار رایگان [PWABuilder](https://www.pwabuilder.com/) یا فریمورک Capacitor، در کمتر از ۵ دقیقه خروجی APK امضا شده برای نصب مستقیم روی هر گوشی اندرویدی بگیرید.

### روش ۳: اجرای محیط کامل لینوکسی با Termux و Termux:X11
برای اجرای نسخه کامل پایتونی روی گوشی:
۱. برنامه‌های **Termux** و **Termux:X11** را از F-Droid نصب کنید.  
۲. اسکریپت `packaging/android/termux_install.sh` را اجرا کنید.  
۳. برنامه Termux:X11 را باز کنید تا فروسیال با فیزیک و رندرر کامل پایتون به صورت ویجت اجرا شود.

</div>

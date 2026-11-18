# FerroWidget for Windows / نسخه ویندوز

[English](#english) | [فارسی](#فارسی)

---

## English

### Quick Installation (Method 1: One-Click Script)
1. Ensure [Python 3.10+](https://www.python.org/downloads/) is installed and check **"Add python.exe to PATH"** during setup.
2. Double-click `install_windows.bat` in this folder.
3. The installer will:
   - Create a dedicated virtual environment in `%LOCALAPPDATA%\FerroWidget\venv`.
   - Install all required libraries (PySide6, ModernGL, NumPy, sounddevice).
   - Create a desktop shortcut `FerroWidget.lnk`.
   - Start the widget in the background.

### Standalone Executable (Method 2: PyInstaller)
To build a standalone `.exe`:
```cmd
pip install pyinstaller
pyinstaller packaging\windows\ferrowidget.spec
```
The resulting executable will be in `dist\ferrowidget.exe`.

### Inno Setup Installer (Method 3)
Open `packaging\windows\ferrowidget_setup.iss` with Inno Setup Compiler and click **Compile** to generate `FerroWidget_Setup.exe`.

---

### Windows Interactive Controls & Modes
FerroWidget on Windows includes two toggleable controls:
1. **⌨️ Typing Reactive Mode (حساس به تایپ)**:
   - When enabled, typing on your keyboard across any Windows app causes the ferrofluid to pulse rhythmically and sprout sharp hexagonal Rosensweig spikes.
   - **Toggle via**:
     - System Tray Icon menu: Check/uncheck `⌨️ حساس به تایپ (Typing Reactive)`
     - Widget overlay button: `[ ⌨️ تایپ: فعال/خاموش ]` in Edit Mode
     - Hotkey: `Ctrl + Shift + T`
     - Command Line / IPC: `ferrowidget ctl typing toggle`
2. **🎤 Microphone Input Mode (روشن کردن میکروفن)**:
   - Switch input source between desktop system audio playback (WASAPI loopback) and live microphone input.
   - **Toggle via**:
     - System Tray Icon menu: Check/uncheck `🎤 روشن کردن میکروفن (Microphone Input)`
     - Widget overlay button: `[ 🎤 میکروفن: فعال/خاموش ]` in Edit Mode
     - Hotkey: `Ctrl + Shift + M`
     - Command Line / IPC: `ferrowidget ctl mic toggle`
3. **Edit Mode (Move / Resize)**:
   - Double-click widget, select `Edit Position & Size` in Tray menu, or press `Ctrl + Shift + E`. Press `Esc` to lock.

---

## فارسی

<div dir="rtl">

### کنترل‌ها و دکمه‌های نسخه ویندوز
در نسخه ویندوز دو دکمه اختصاصی برای فعال‌سازی حالات زیر اضافه شده است:
۱. **⌨️ حساس به تایپ کیبورد (Typing Reactive)**:  
   - با فعال کردن این گزینه، هنگام تایپ کردن در هر برنامه‌ای از ویندوز (مثل مرورگر، ورد، تلگرام یا کدنویسی)، مایع فروسیال پالس زده و خارهای تیز روزنزویگ از آن جوانه می‌زنند.
   - **روش‌های فعال/غیرفعال‌سازی**:
     - کلیک راست روی آیکون برنامه در تسک‌بار (System Tray) و انتخاب تیک «⌨️ حساس به تایپ (Typing Reactive)».
     - دکمه شیشه‌ای روی خود ویجت در حالت ویرایش: `[ ⌨️ تایپ: فعال/خاموش ]`.
     - کلید میانبر سریع: `Ctrl + Shift + T`.
     - خط فرمان: `ferrowidget ctl typing toggle`.

۲. **🎤 روشن کردن میکروفن و حساس به صدای ورودی (Microphone Input)**:  
   - با فعال کردن این گزینه، ویجت به جای صدای خروجی سیستم، مستقیماً به صدای میکروفن و صدای محیط واکنش نشان می‌دهد.
   - **روش‌های فعال/غیرفعال‌سازی**:
     - کلیک راست روی آیکون تسک‌بار و انتخاب تیک «🎤 روشن کردن میکروفن (Microphone Input)».
     - دکمه شیشه‌ای روی ویجت در حالت ویرایش: `[ 🎤 میکروفن: فعال/خاموش ]`.
     - کلید میانبر سریع: `Ctrl + Shift + M`.
     - خط فرمان: `ferrowidget ctl mic toggle`.

۳. **حالت تغییر اندازه و جابه‌جایی (Edit Mode)**:
   - با دوبار کلیک روی ویجت یا انتخاب گزینه اول منوی تسک‌بار، کادر ویرایش باز شده و دکمه‌ها روی صفحه ظاهر می‌شوند. برای قفل شدن روی دسکتاپ کافیست کلید `Esc` را بزنید.

### روش ۱: نصب سریع با یک کلیک (پیشنهادی)
۱. مطمئن شوید [Python 3.10+](https://www.python.org/downloads/) روی ویندوز نصب است و هنگام نصب حتماً تیک **"Add python.exe to PATH"** را زده‌اید.  
۲. روی فایل `install_windows.bat` دوبار کلیک کنید.  
۳. برنامه به طور خودکار:
   - محیط اختصاصی پایتون در پوشه برنامه‌ها ایجاد می‌کند.
   - پیش‌نیازهای گرافیکی و صوتی را نصب می‌کند.
   - آیکون میانبر «FerroWidget» را روی دسکتاپ قرار می‌دهد.
   - برنامه را بدون باز ماندن پنجره خط فرمان در پس‌زمینه اجرا می‌کند.

### روش ۲: فایل اجرایی مستقل (.exe)
برای ساخت فایل مستقل بدون نیاز به پایتون:
```cmd
pip install pyinstaller
pyinstaller packaging\windows\ferrowidget.spec
```
فایل خروجی در مسیر `dist\ferrowidget.exe` ایجاد می‌شود.

### روش ۳: فایل نصبی استاندارد ویندوز (Setup.exe)
با استفاده از نرم‌افزار Inno Setup، فایل `ferrowidget_setup.iss` را کامپایل کنید تا نصاب گرافیکی ویندوز ساخته شود.

</div>

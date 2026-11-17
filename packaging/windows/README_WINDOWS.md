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

## فارسی

<div dir="rtl">

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

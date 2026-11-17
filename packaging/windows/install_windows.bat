@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo          FerroWidget Windows Installer
echo   Real-Time Ferrofluid Desktop Audio Visualizer
echo =======================================================
echo.

:: 1. Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Python 3 was not found in PATH.
    echo Trying to find python in standard installation paths...
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python310;%LOCALAPPDATA%\Programs\Python\Python310\Scripts;%PATH%"
    ) else (
        echo [ERROR] Python is not installed or not in PATH!
        echo Please install Python 3.10 or newer from https://www.python.org/
        echo Make sure to check "Add python.exe to PATH" during installation.
        pause
        exit /b 1
    )
)

:: 2. Set Paths
set "SCRIPT_DIR=%~dp0"
set "APP_DIR=%LOCALAPPDATA%\FerroWidget"
set "VENV_DIR=%APP_DIR%\venv"
set "SRC_DIR=%SCRIPT_DIR%..\.."

echo [1/4] Preparing installation directory at %APP_DIR%...
if not exist "%APP_DIR%" mkdir "%APP_DIR%"

:: 3. Create Virtualenv
echo [2/4] Setting up Python virtual environment...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    python -m venv "%VENV_DIR%"
)

:: 4. Install Dependencies & Package
echo [3/4] Installing dependencies (PySide6, ModernGL, NumPy, sounddevice)...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\pip.exe" install PySide6 moderngl numpy sounddevice tomli-w pillow

:: Check if installing from standalone zip bundle (wheel present) or git repo
set "WHEEL_INSTALLED=0"
for %%F in ("%SCRIPT_DIR%ferrowidget-*.whl") do (
    if exist "%%F" (
        echo Installing from bundled wheel: %%~nxF
        "%VENV_DIR%\Scripts\pip.exe" install --no-deps "%%F"
        set "WHEEL_INSTALLED=1"
    )
)

if "%WHEEL_INSTALLED%"=="0" (
    if exist "%SCRIPT_DIR%pyproject.toml" (
        echo Installing from current directory source...
        "%VENV_DIR%\Scripts\pip.exe" install "%SCRIPT_DIR%"
    ) else if exist "%SRC_DIR%\pyproject.toml" (
        echo Installing from git repo source...
        "%VENV_DIR%\Scripts\pip.exe" install -e "%SRC_DIR%"
    ) else (
        echo [ERROR] Could not find ferrowidget wheel or pyproject.toml!
        pause
        exit /b 1
    )
)

:: 5. Copy Icon
set "ICON_SRC="
if exist "%SCRIPT_DIR%ferrowidget.ico" (
    set "ICON_SRC=%SCRIPT_DIR%ferrowidget.ico"
) else if exist "%SRC_DIR%\packaging\icons\ferrowidget.ico" (
    set "ICON_SRC=%SRC_DIR%\packaging\icons\ferrowidget.ico"
)

if defined ICON_SRC (
    copy /y "%ICON_SRC%" "%APP_DIR%\ferrowidget.ico" >nul
)

if exist "%SCRIPT_DIR%ferrowidget.png" (
    copy /y "%SCRIPT_DIR%ferrowidget.png" "%APP_DIR%\ferrowidget.png" >nul
) else if exist "%SRC_DIR%\packaging\icons\ferrowidget.png" (
    copy /y "%SRC_DIR%\packaging\icons\ferrowidget.png" "%APP_DIR%\ferrowidget.png" >nul
)

:: 6. Create Silent VBScript Launcher (no cmd window)
echo [4/4] Creating desktop shortcuts and background launcher...
set "LAUNCHER_VBS=%APP_DIR%\run_ferrowidget.vbs"
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.Run """%VENV_DIR%\Scripts\pythonw.exe"" -m ferrowidget run", 0, False
) > "%LAUNCHER_VBS%"

:: Batch Launcher
set "LAUNCHER_BAT=%APP_DIR%\ferrowidget.bat"
(
echo @echo off
echo "%VENV_DIR%\Scripts\python.exe" -m ferrowidget %%*
) > "%LAUNCHER_BAT%"

:: Create Desktop Shortcut via PowerShell with Icon
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'FerroWidget.lnk')); " ^
  "$s.TargetPath = '%LAUNCHER_VBS%'; " ^
  "$s.WorkingDirectory = '%APP_DIR%'; " ^
  "if (Test-Path '%APP_DIR%\ferrowidget.ico') { $s.IconLocation = '%APP_DIR%\ferrowidget.ico,0' }; " ^
  "$s.Save()"

echo.
echo =======================================================
echo  FerroWidget installed successfully!
echo  Desktop shortcut "FerroWidget" has been created.
echo  Starting FerroWidget now...
echo =======================================================
start "" "%LAUNCHER_VBS%"

@echo off
setlocal
set "APP_DIR=%LOCALAPPDATA%\FerroWidget"
set "VENV_DIR=%APP_DIR%\venv"

if exist "%VENV_DIR%\Scripts\pythonw.exe" (
    start "" "%VENV_DIR%\Scripts\pythonw.exe" -m ferrowidget run %*
) else (
    echo FerroWidget is not installed yet. Running installer...
    call "%~dp0install_windows.bat"
)

@echo off
setlocal
echo === FX Backend: optional ML packages ===
echo TensorFlow ~390 MB + PyTorch ~203 MB. Network must be stable.
echo Core backend (install.bat) works WITHOUT these packages.
echo.

if not exist .venv\Scripts\pip.exe (
    echo ERROR: .venv not found. Run install.bat first.
    exit /b 1
)

where powershell >nul 2>&1
if errorlevel 1 (
    echo ERROR: PowerShell required for install-ml.ps1
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-ml.ps1" %*
exit /b %ERRORLEVEL%

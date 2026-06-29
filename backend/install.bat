@echo off
setlocal
echo === FX Backend: Python 3.12 venv ===
echo.
echo NOTE: Python 3.14 is NOT supported on Windows.
echo       Use Python 3.12 virtual environment.
echo.

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: py launcher not found. Install Python 3.12 from https://www.python.org/downloads/
    exit /b 1
)

py -3.12 -c "import sys" 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.12 not found. Install Python 3.12 from https://www.python.org/downloads/
    exit /b 1
)

if not exist .venv (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        exit /b 1
    )
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install --retries 5 --timeout 120 -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed.
    exit /b 1
)

echo.
echo === Core install complete ===
echo.
echo TensorFlow/PyTorch are OPTIONAL and NOT included here.
echo To install them later:  install-ml.bat
echo.
echo Activate with:  .venv\Scripts\activate
echo Run backend:    python run.py
endlocal

@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3 and add it to PATH.
    pause
    exit /b 1
)

echo Installing flasher requirements...
python -m pip install -r flasher\requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

python -m flasher %*
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% neq 0 pause
exit /b %EXIT_CODE%

@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Missing %PY%. Run the environment setup first.
    pause
    exit /b 2
)
echo Read-only audit: C:\AFM_Automation\OLD input IMAGES
"%PY%" tools\audit_raw_dataset.py %*
set "STATUS=%ERRORLEVEL%"
echo.
echo Status: %STATUS%. Upload only CHATGPT_REVIEW.zip, never PRIVATE_manifest.csv.
pause
exit /b %STATUS%

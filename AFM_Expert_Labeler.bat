@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo Python GUI environment not found under C:\AFM_image_wizard\.venv
  echo Install the project dependencies before launching the labeler.
  pause
  exit /b 2
)
start "" "%PY%" -m afm_copilot.labeler
exit /b 0

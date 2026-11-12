@echo off
rem One local entrypoint for AFM Copilot desktop workbench.
rem All functionality uses this checkout's Python 3 virtual environment.
rem No archive reorganization, deletion, Git push or batch conversion at startup.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo AFM Copilot virtual environment not found.
  echo Expected: %PY%
  echo Run Python setup in C:\AFM_image_wizard before launching.
  pause
  exit /b 2
)
start "" "%PY%" -m afm_copilot.launcher
exit /b 0

@echo off
setlocal
cd /d "%~dp0"
set "PY=%CD%\.venv\Scripts\python.exe"
if exist "%PY%" goto ready
echo Creating the one AFM Copilot Python environment...
where py.exe >nul 2>nul
if not errorlevel 1 (
  py -3.11 -m venv "%CD%\.venv"
  if exist "%PY%" goto ready
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  python.exe -c "import sys; assert sys.version_info[:2] == (3, 11)"
  if not errorlevel 1 python.exe -m venv "%CD%\.venv"
  if exist "%PY%" goto ready
)
where winget.exe >nul 2>nul
if errorlevel 1 goto missing
echo Python 3.11 not found. Installing via Windows Package Manager...
winget install --id Python.Python.3.11 --exact --source winget --accept-source-agreements --accept-package-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -m venv "%CD%\.venv"
)
if not exist "%PY%" if exist "%ProgramFiles%\Python311\python.exe" (
  "%ProgramFiles%\Python311\python.exe" -m venv "%CD%\.venv"
)
if not exist "%PY%" goto missing
:ready
rem Use python.exe so installation and diagnostic errors remain visible.
rem All dependencies and launcher logic live in afm_copilot.bootstrap.
"%PY%" -m afm_copilot.bootstrap %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo AFM Copilot did not complete. Exit code: %RC%
  pause
)
exit /b %RC%
:missing
echo Python 3.11 environment could not be created. Check the installation output above.
pause
exit /b 2

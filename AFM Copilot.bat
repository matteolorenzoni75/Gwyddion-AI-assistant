@echo off
rem Launch the AFM Copilot desktop application.
rem
rem Uses the project's own interpreter by full path on purpose: a bare
rem "python" on this machine resolves to Gwyddion's Python 2.7, which cannot
rem run this application.

setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo.
    echo Cannot find %PY%
    echo.
    echo Set the environment up first, from a PowerShell window:
    echo     cd "%HERE%"
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -e .
    echo.
    pause
    exit /b 1
)

start "" "%PY%" -m afm_copilot.gui
endlocal

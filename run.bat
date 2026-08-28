@echo off
REM  Start Michi. Pass any flag through, e.g.  run.bat --text
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo  Virtual environment missing. Run setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\python.exe -m michi %*

if errorlevel 1 pause

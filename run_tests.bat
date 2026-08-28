@echo off
REM  Offline test suite — no microphone, no API calls, no network.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    call .venv\Scripts\python.exe -m tests.run_all
) else (
    python -m tests.run_all
)

pause

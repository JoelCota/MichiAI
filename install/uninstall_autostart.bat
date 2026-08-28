@echo off
REM  Remove the logon task created by install_autostart.bat
setlocal

set TASKNAME=Michi Voice Assistant

schtasks /query /tn "%TASKNAME%" >nul 2>nul
if errorlevel 1 (
    echo  No autostart task found — nothing to remove.
    pause
    exit /b 0
)

schtasks /delete /tn "%TASKNAME%" /f
if errorlevel 1 (
    echo  [X] Couldn't remove the task. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo  Autostart removed. Michi will no longer start at logon.
echo.
pause

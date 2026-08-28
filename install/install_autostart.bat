@echo off
REM ---------------------------------------------------------------
REM  Start Michi automatically when you log in.
REM  Uses Task Scheduler so she starts hidden, with no console window.
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set TASKNAME=Michi Voice Assistant
set LAUNCHER=%CD%\install\michi_silent.vbs

echo.
echo  Michi autostart
echo  ===============
echo.

if not exist ".venv\Scripts\pythonw.exe" (
    echo  [X] Michi isn't set up yet. Run setup.bat first.
    pause
    exit /b 1
)

schtasks /query /tn "%TASKNAME%" >nul 2>nul
if not errorlevel 1 (
    echo  An autostart task already exists. Replacing it...
    schtasks /delete /tn "%TASKNAME%" /f >nul
)

schtasks /create ^
  /tn "%TASKNAME%" ^
  /tr "wscript.exe \"%LAUNCHER%\"" ^
  /sc onlogon ^
  /rl limited ^
  /f

if errorlevel 1 (
    echo.
    echo  [X] Couldn't create the task.
    echo      Try running this file as Administrator.
    pause
    exit /b 1
)

echo.
echo  Done. Michi will start hidden each time you log in,
echo  with a tray icon you can pause or quit her from.
echo.
echo  Start her now without rebooting:  schtasks /run /tn "%TASKNAME%"
echo  Undo this later:                  install\uninstall_autostart.bat
echo.
pause

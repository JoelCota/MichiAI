@echo off
REM ---------------------------------------------------------------
REM  Michi — one-time setup. Run this once, then use run.bat.
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo.
echo  Michi setup
echo  ===========
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo  [X] Python was not found on PATH.
    echo      Install Python 3.10+ from python.org and tick "Add to PATH".
    pause
    exit /b 1
)

if not exist ".venv" (
    echo  [1/4] Creating virtual environment...
    python -m venv .venv
) else (
    echo  [1/4] Virtual environment already exists.
)

echo  [2/4] Upgrading pip...
call .venv\Scripts\python.exe -m pip install --upgrade pip --quiet

echo  [3/4] Installing dependencies (this takes a few minutes)...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [X] Some packages failed to install. Scroll up for the reason.
    pause
    exit /b 1
)

REM NVIDIA GPU present? Install cuBLAS so CUDA transcription works, and copy
REM the DLL next to ctranslate2 (its loader doesn't search the pip package dir).
set HAS_NVIDIA=0
wmic path win32_VideoController get name 2>nul | findstr /i "nvidia" >nul && set HAS_NVIDIA=1
where nvidia-smi >nul 2>nul && set HAS_NVIDIA=1
if "%HAS_NVIDIA%"=="1" (
    echo  [3.5/4] NVIDIA GPU found - installing cuBLAS for CUDA transcription...
    call .venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 --quiet
    if not errorlevel 1 (
        copy /y ".venv\Lib\site-packages\nvidia\cublas\bin\cublas64_12.dll" ".venv\Lib\site-packages\ctranslate2\" >nul
        copy /y ".venv\Lib\site-packages\nvidia\cublas\bin\cublasLt64_12.dll" ".venv\Lib\site-packages\ctranslate2\" >nul
        echo      cuBLAS ready.
    ) else (
        echo      [i] cuBLAS install failed (no internet?). Use device: cpu in config.yaml, or re-run setup later.
    )
)

if not exist ".env" (
    echo  [4/4] Creating .env from the template...
    copy /y ".env.example" ".env" >nul
    echo.
    echo  ^>^> Now open .env and paste in your API key.
) else (
    echo  [4/4] .env already exists.
)

echo.
echo  Done. Checking your config:
echo.
call .venv\Scripts\python.exe -m michi --check

echo.
echo  ---------------------------------------------------------------
echo   Next steps
echo   1. Put your API key in  .env
echo   2. run.bat --doctor    (tests mic, speech, model and voice)
echo   3. run.bat             (say the wake word)
echo  ---------------------------------------------------------------
echo.
pause

@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

REM StreamCuter - Quick start batch file for Windows
REM Usage:
REM   run_local.bat --input "D:\video.mp4" --clips 3

echo ============================================
echo   StreamCuter - Vertical Clip Generator
echo ============================================
echo.

REM Check Python first.
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ first.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Prefer ffmpeg/ffprobe already available in PATH. Bootstrap only if both PATH and local tools are missing.
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "tools\ffmpeg\bin\ffmpeg.exe" (
        echo Using bundled ffmpeg from tools\ffmpeg\bin
        set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
    ) else (
        echo ffmpeg was not found in PATH. Bootstrapping ffmpeg into tools\ffmpeg...
        powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap.ps1" -ProjectDir "%CD%"
        if exist "tools\ffmpeg\bin\ffmpeg.exe" (
            set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
        )
        echo.
    )
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffmpeg is still not available.
    echo Install ffmpeg from https://ffmpeg.org/download.html or fix tools\ffmpeg.
    pause
    exit /b 1
)

ffprobe -version >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffprobe is not available.
    echo Install ffmpeg from https://ffmpeg.org/download.html or fix tools\ffmpeg.
    pause
    exit /b 1
)

REM Install dependencies if needed.
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    call "venv\Scripts\activate.bat"
    echo Installing dependencies...
    pip install -r requirements.txt
) else (
    call "venv\Scripts\activate.bat"
)

echo.
echo Running StreamCuter with args: %*
echo.

python -m app.main %*
set "SC_EXIT=%ERRORLEVEL%"

echo.
if "%SC_EXIT%"=="0" (
    echo Done. Check the output folder for results.
) else (
    echo StreamCuter failed with exit code %SC_EXIT%.
)
pause
exit /b %SC_EXIT%

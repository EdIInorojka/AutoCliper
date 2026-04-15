@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHONUTF8=1"

echo ============================================
echo   StreamCuter - Windows launcher
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found. Install Python 3.11+ first.
    echo https://www.python.org/downloads/
    if "%SC_PAUSE%"=="1" pause
    exit /b 1
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "tools\ffmpeg\bin\ffmpeg.exe" (
        echo Using local ffmpeg from tools\ffmpeg\bin
        set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
    ) else (
        echo ffmpeg was not found in PATH. Bootstrapping into tools\ffmpeg...
        powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap.ps1" -ProjectDir "%CD%"
        if exist "tools\ffmpeg\bin\ffmpeg.exe" (
            set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
        )
        echo.
    )
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffmpeg is still unavailable.
    echo Install ffmpeg or check tools\ffmpeg\bin.
    if "%SC_PAUSE%"=="1" pause
    exit /b 1
)

ffprobe -version >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffprobe is unavailable.
    echo Install ffmpeg or check tools\ffmpeg\bin.
    if "%SC_PAUSE%"=="1" pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: failed to create venv.
        if "%SC_PAUSE%"=="1" pause
        exit /b 1
    )
)

call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: failed to activate venv.
    if "%SC_PAUSE%"=="1" pause
    exit /b 1
)

set "SC_NEED_DEPS=0"
python -c "import rich, yaml, cv2, numpy" >nul 2>&1
if errorlevel 1 set "SC_NEED_DEPS=1"
if not exist "venv\.streamcuter_deps_installed" set "SC_NEED_DEPS=1"

if "%SC_NEED_DEPS%"=="1" (
    python -c "import rich, yaml, cv2, numpy" >nul 2>&1
    if errorlevel 1 (
        echo Installing Python dependencies...
        python -m pip install --upgrade pip
        if errorlevel 1 (
            echo ERROR: failed to upgrade pip.
            if "%SC_PAUSE%"=="1" pause
            exit /b 1
        )
        python -m pip install -r requirements.txt
        if errorlevel 1 (
            echo ERROR: failed to install requirements.
            if "%SC_PAUSE%"=="1" pause
            exit /b 1
        )
    )
    echo ok>"venv\.streamcuter_deps_installed"
)

echo.
if /I "%~1"=="--wizard" (
    echo Starting StreamCuter wizard...
    echo.
    python -m app.wizard
) else (
    echo Starting StreamCuter CLI:
    echo   python -m app.main %*
    echo.
    python -m app.main %*
)
set "SC_EXIT=%ERRORLEVEL%"

echo.
if "%SC_EXIT%"=="0" (
    echo Done.
) else (
    echo StreamCuter finished with error code %SC_EXIT%.
)

if "%SC_PAUSE%"=="1" pause
exit /b %SC_EXIT%

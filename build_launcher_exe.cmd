@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   StreamCuter - build launcher EXE
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ first.
    pause
    exit /b 1
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: failed to install PyInstaller.
        pause
        exit /b 1
    )
)

echo Building StreamCuter.exe...
python -m PyInstaller ^
  --onefile ^
  --console ^
  --clean ^
  --noconfirm ^
  --name StreamCuter ^
  --distpath "%CD%" ^
  --workpath "%CD%\build\launcher" ^
  --specpath "%CD%\build\launcher" ^
  "%CD%\streamcuter_exe_launcher.py"

if errorlevel 1 (
    echo ERROR: build failed.
    pause
    exit /b 1
)

echo.
echo Done:
echo   %CD%\StreamCuter.exe
echo.
echo Double-click StreamCuter.exe to open the generation wizard.
pause

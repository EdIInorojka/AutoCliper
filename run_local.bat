@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

REM StreamCuter - быстрый запуск под Windows
REM Пример:
REM   run_local.bat --input "D:\video.mp4" --clips 3

echo ============================================
echo   StreamCuter - генератор вертикальных клипов
echo ============================================
echo.

REM Check Python first.
python --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден. Сначала установи Python 3.11+.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Сначала используем ffmpeg/ffprobe из PATH. Скачиваем локально только если их нет.
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "tools\ffmpeg\bin\ffmpeg.exe" (
        echo Использую локальный ffmpeg из tools\ffmpeg\bin
        set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
    ) else (
        echo ffmpeg не найден в PATH. Скачиваю ffmpeg в tools\ffmpeg...
        powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap.ps1" -ProjectDir "%CD%"
        if exist "tools\ffmpeg\bin\ffmpeg.exe" (
            set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
        )
        echo.
    )
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: ffmpeg всё ещё недоступен.
    echo Установи ffmpeg с https://ffmpeg.org/download.html или проверь tools\ffmpeg.
    pause
    exit /b 1
)

ffprobe -version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: ffprobe недоступен.
    echo Установи ffmpeg с https://ffmpeg.org/download.html или проверь tools\ffmpeg.
    pause
    exit /b 1
)

REM Ставим зависимости при первом запуске.
if not exist "venv" (
    echo Создаю виртуальное окружение...
    python -m venv venv
    call "venv\Scripts\activate.bat"
    echo Устанавливаю зависимости...
    pip install -r requirements.txt
) else (
    call "venv\Scripts\activate.bat"
)

echo.
echo Запускаю StreamCuter с аргументами: %*
echo.

python -m app.main %*
set "SC_EXIT=%ERRORLEVEL%"

echo.
if "%SC_EXIT%"=="0" (
    echo Готово. Проверь папку output или выбранную папку выгрузки.
) else (
    echo StreamCuter завершился с ошибкой. Код: %SC_EXIT%.
)
pause
exit /b %SC_EXIT%

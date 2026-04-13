@echo off
setlocal
cd /d "%~dp0"

REM Полный E2E на вашем MP4 (длинные файлы внутри теста режутся до 180 сек по умолчанию).
REM Требования: Python 3.11+, ffmpeg/ffprobe в PATH или tools\ffmpeg\bin,
REM             pip install -r requirements-local.txt

set STREAMCUTER_RUN_E2E=1
if "%STREAMCUTER_TEST_VIDEO%"=="" (
  set "STREAMCUTER_TEST_VIDEO=%~dp0Your Biggest Slot Wins – #84  2025.mp4"
)

if exist "venv\Scripts\python.exe" (
  call venv\Scripts\activate.bat
)

python -m unittest -v tests.test_integration_e2e.TestIntegrationE2E.test_pipeline_on_short_slice_of_slot_wins
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 exit /b %ERR%
echo OK. Смотри клипы в output\_e2e_test\
exit /b 0

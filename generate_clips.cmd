@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   StreamCuter - clip generation wizard
echo ============================================
echo.

set "SC_INPUT="
set /p "SC_INPUT=1. Video path or YouTube/Kick URL: "
if not defined SC_INPUT (
    echo ERROR: input is empty.
    pause
    exit /b 1
)

echo.
echo 2. Subtitle and CTA language:
echo    [1] Russian
echo    [2] English
choice /C 12 /N /M "Choice: "
set "SC_LANG=ru"
if errorlevel 2 set "SC_LANG=en"

echo.
set "SC_VOICE="
set /p "SC_VOICE=3. CTA voice mp3/wav path (Enter = none): "
if defined SC_VOICE (
    if not exist "%SC_VOICE%" (
        echo WARNING: CTA voice file was not found. Continuing without it:
        echo   %SC_VOICE%
        set "SC_VOICE="
    )
)

echo.
set "SC_OUT="
set /p "SC_OUT=4. Output folder (Enter = output\generated): "
if not defined SC_OUT set "SC_OUT=output\generated"

echo.
set "SC_CLIPS="
set /p "SC_CLIPS=5. Number of clips (Enter = 5): "
if not defined SC_CLIPS set "SC_CLIPS=5"

echo.
echo 6. Delete source video after successful render?
echo    [1] Yes
echo    [2] No
choice /C 12 /N /M "Choice: "
set "SC_DELETE_SOURCE=--delete-input-after-success"
if errorlevel 2 set "SC_DELETE_SOURCE="

echo.
echo ============================================
echo   Starting generation
echo ============================================
echo Input:       %SC_INPUT%
echo Language:    %SC_LANG%
echo CTA voice:   %SC_VOICE%
echo Output dir:  %SC_OUT%
echo Clips:       %SC_CLIPS%
echo Music:       off
if defined SC_DELETE_SOURCE (
    echo Delete src:  yes
) else (
    echo Delete src:  no
)
echo.
echo Pipeline logs: prerequisites, ingest, probe, webcam, ASR, highlights, render, cleanup.
echo.

if defined SC_VOICE (
    call "%~dp0run_local.bat" --input "%SC_INPUT%" --subtitle-lang %SC_LANG% --cta-lang %SC_LANG% --cta-voice "%SC_VOICE%" --output-dir "%SC_OUT%" --clips %SC_CLIPS% --no-music %SC_DELETE_SOURCE%
) else (
    call "%~dp0run_local.bat" --input "%SC_INPUT%" --subtitle-lang %SC_LANG% --cta-lang %SC_LANG% --output-dir "%SC_OUT%" --clips %SC_CLIPS% --no-music %SC_DELETE_SOURCE%
)

endlocal

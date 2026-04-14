@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   StreamCuter - мастер генерации клипов
echo ============================================
echo.

set "SC_INPUT="
set /p "SC_INPUT=1. Путь к видео или ссылка YouTube/Kick: "
if not defined SC_INPUT (
    echo ОШИБКА: путь или ссылка не указаны.
    pause
    exit /b 1
)

echo.
echo 2. Язык субтитров и надписи при паузе:
echo    [1] Русский
echo    [2] Английский
choice /C 12 /N /M "Выбор: "
set "SC_LANG=ru"
if errorlevel 2 set "SC_LANG=en"

echo.
echo 3. Надпись при зависании видео:
echo    [1] Стандартные надписи из файла
echo    [2] Своя надпись
choice /C 12 /N /M "Выбор: "
set "SC_CTA_FLAG=--cta-text-mode"
set "SC_CTA_VALUE=file"
if errorlevel 2 (
    set "SC_CTA_TEXT="
    set /p "SC_CTA_TEXT=Введите свою надпись: "
    if defined SC_CTA_TEXT (
        set "SC_CTA_FLAG=--cta-text"
        set "SC_CTA_VALUE=%SC_CTA_TEXT%"
    ) else (
        set "SC_CTA_FLAG=--cta-text-mode"
        set "SC_CTA_VALUE=file"
    )
)

echo.
set "SC_VOICE="
set /p "SC_VOICE=4. Файл озвучки паузы mp3/wav (Enter = без озвучки): "
if defined SC_VOICE (
    if not exist "%SC_VOICE%" (
        echo ВНИМАНИЕ: файл озвучки не найден, продолжаю без него:
        echo   %SC_VOICE%
        set "SC_VOICE="
    )
)

echo.
set "SC_OUT="
set /p "SC_OUT=5. Папка для готовых видео (Enter = output\generated): "
if not defined SC_OUT set "SC_OUT=output\generated"

echo.
set "SC_CLIPS="
set /p "SC_CLIPS=6. Количество клипов (Enter = 5): "
if not defined SC_CLIPS set "SC_CLIPS=5"

echo.
echo 7. Качество рендера:
echo    [1] Баланс
echo    [2] Быстро
echo    [3] Максимальное качество
echo    [4] Маленький размер
echo    [5] Быстро через NVIDIA
choice /C 12345 /N /M "Выбор: "
set "SC_RENDER_PRESET=balanced"
if errorlevel 5 set "SC_RENDER_PRESET=nvenc_fast"
if errorlevel 4 if not errorlevel 5 set "SC_RENDER_PRESET=small"
if errorlevel 3 if not errorlevel 4 set "SC_RENDER_PRESET=quality"
if errorlevel 2 if not errorlevel 3 set "SC_RENDER_PRESET=fast"
set "SC_RENDER_ARGS=--render-preset %SC_RENDER_PRESET%"

echo.
echo 8. Сделать только быстрый предпросмотр одного клипа?
echo    [1] Да
echo    [2] Нет, сразу полная генерация
choice /C 12 /N /M "Выбор: "
set "SC_QUICK_PREVIEW=--quick-preview"
if errorlevel 2 set "SC_QUICK_PREVIEW="

echo.
echo 9. Открыть окно выбора вебки/слота?
echo    [1] Да
echo    [2] Нет, использовать авторазметку
choice /C 12 /N /M "Выбор: "
set "SC_PREVIEW=--preview-layout"
if errorlevel 2 set "SC_PREVIEW="
set "SC_PREVIEW_TIME="
if defined SC_PREVIEW (
    set /p "SC_PREVIEW_TIME=Момент предпросмотра (Enter = середина, примеры: 180 или 03:00): "
)

echo.
echo 10. Удалить исходное видео после успешной генерации?
echo    [1] Да
echo    [2] Нет
choice /C 12 /N /M "Выбор: "
set "SC_DELETE_SOURCE=--delete-input-after-success"
if errorlevel 2 set "SC_DELETE_SOURCE="

echo.
echo ============================================
echo   Запускаю генерацию
echo ============================================
echo Видео:        %SC_INPUT%
echo Язык:         %SC_LANG%
if "%SC_CTA_FLAG%"=="--cta-text" (
    echo CTA текст:    %SC_CTA_VALUE%
) else (
    echo CTA текст:    стандартный файл
)
echo Озвучка CTA:  %SC_VOICE%
echo Папка:        %SC_OUT%
echo Клипов:       %SC_CLIPS%
echo Рендер:       %SC_RENDER_PRESET%
if defined SC_QUICK_PREVIEW (
    echo Быстрый preview: да
) else (
    echo Быстрый preview: нет
)
if defined SC_PREVIEW (
    echo Разметка UI:   да
    if defined SC_PREVIEW_TIME echo Кадр UI:      %SC_PREVIEW_TIME%
) else (
    echo Разметка UI:   нет
)
echo Музыка:       выкл
if defined SC_DELETE_SOURCE (
    echo Удалить src:  да
) else (
    echo Удалить src:  нет
)
echo.
echo Этапы: проверка, вход, анализ, вебка/слот, ASR, хайлайты, рендер, очистка.
echo.

if defined SC_VOICE (
    if defined SC_PREVIEW_TIME (
        call "%~dp0run_local.bat" --input "%SC_INPUT%" --subtitle-lang %SC_LANG% --cta-lang %SC_LANG% %SC_CTA_FLAG% "%SC_CTA_VALUE%" --cta-voice "%SC_VOICE%" --output-dir "%SC_OUT%" --clips %SC_CLIPS% %SC_RENDER_ARGS% %SC_QUICK_PREVIEW% --no-music %SC_PREVIEW% --preview-time "%SC_PREVIEW_TIME%" %SC_DELETE_SOURCE%
    ) else (
        call "%~dp0run_local.bat" --input "%SC_INPUT%" --subtitle-lang %SC_LANG% --cta-lang %SC_LANG% %SC_CTA_FLAG% "%SC_CTA_VALUE%" --cta-voice "%SC_VOICE%" --output-dir "%SC_OUT%" --clips %SC_CLIPS% %SC_RENDER_ARGS% %SC_QUICK_PREVIEW% --no-music %SC_PREVIEW% %SC_DELETE_SOURCE%
    )
) else (
    if defined SC_PREVIEW_TIME (
        call "%~dp0run_local.bat" --input "%SC_INPUT%" --subtitle-lang %SC_LANG% --cta-lang %SC_LANG% %SC_CTA_FLAG% "%SC_CTA_VALUE%" --output-dir "%SC_OUT%" --clips %SC_CLIPS% %SC_RENDER_ARGS% %SC_QUICK_PREVIEW% --no-music %SC_PREVIEW% --preview-time "%SC_PREVIEW_TIME%" %SC_DELETE_SOURCE%
    ) else (
        call "%~dp0run_local.bat" --input "%SC_INPUT%" --subtitle-lang %SC_LANG% --cta-lang %SC_LANG% %SC_CTA_FLAG% "%SC_CTA_VALUE%" --output-dir "%SC_OUT%" --clips %SC_CLIPS% %SC_RENDER_ARGS% %SC_QUICK_PREVIEW% --no-music %SC_PREVIEW% %SC_DELETE_SOURCE%
    )
)

endlocal

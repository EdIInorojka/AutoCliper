@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "SC_PAUSE=1"

call "%~dp0run_local.bat" --wizard
exit /b %ERRORLEVEL%

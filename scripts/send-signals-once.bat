@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

"%SIGNALPILOT_PYTHON%" -m signalpilot --symbols BTCUSDT ETHUSDT SOLUSDT --notify
if errorlevel 1 goto fail

goto end

:fail
echo.
echo SignalPilot could not send signals.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

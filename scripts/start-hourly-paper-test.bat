@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

echo Starting hourly paper-test with Telegram notifications.
echo Keep this window open. Close it to stop.
echo.
"%SIGNALPILOT_PYTHON%" -m signalpilot --paper-loop --symbols BTCUSDT ETHUSDT SOLUSDT --run-every-minutes 60 --notify
if errorlevel 1 goto fail

goto end

:fail
echo.
echo SignalPilot hourly paper-test could not start.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

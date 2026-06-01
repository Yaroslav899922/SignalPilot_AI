@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

echo Starting SignalPilot Telegram bot.
echo Keep this window open while you want the bot to answer.
echo.
"%SIGNALPILOT_PYTHON%" -m signalpilot --telegram-bot
if errorlevel 1 goto fail

goto end

:fail
echo.
echo SignalPilot could not start.
echo If this is first setup, run scripts\setup-telegram-env.bat first.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

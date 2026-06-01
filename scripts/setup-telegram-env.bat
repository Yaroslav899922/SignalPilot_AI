@echo off
setlocal

echo SignalPilot Telegram setup
echo.
echo Paste your bot token from BotFather.
set /p SIGNALPILOT_TOKEN_INPUT=TELEGRAM_BOT_TOKEN: 

if "%SIGNALPILOT_TOKEN_INPUT%"=="" (
    echo Token is empty.
    goto end
)

echo.
echo Paste your channel/chat id. For a public channel it can be like @your_channel.
set /p SIGNALPILOT_CHAT_INPUT=TELEGRAM_CHAT_ID: 

if "%SIGNALPILOT_CHAT_INPUT%"=="" (
    echo Chat id is empty.
    goto end
)

setx TELEGRAM_BOT_TOKEN "%SIGNALPILOT_TOKEN_INPUT%"
if errorlevel 1 goto fail

setx TELEGRAM_CHAT_ID "%SIGNALPILOT_CHAT_INPUT%"
if errorlevel 1 goto fail

echo.
echo Done. Close this window, then start scripts\start-telegram-bot.bat.
goto end

:fail
echo.
echo Could not save Telegram settings.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

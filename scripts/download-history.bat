@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

echo.
echo Downloading Binance history for BTC/ETH/SOL (4h + 15m).
echo This may take a few minutes. Please leave this window open.
echo.

"%SIGNALPILOT_PYTHON%" -m signalpilot.rig.download
if errorlevel 1 goto fail

goto end

:fail
echo.
echo Download failed. Please copy the text above and send it to Claude.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

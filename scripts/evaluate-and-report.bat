@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

"%SIGNALPILOT_PYTHON%" -m signalpilot --evaluate --lookahead-candles 6
if errorlevel 1 goto fail

"%SIGNALPILOT_PYTHON%" -m signalpilot --report
if errorlevel 1 goto fail

goto end

:fail
echo.
echo SignalPilot could not evaluate the journal.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

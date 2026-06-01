@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

"%SIGNALPILOT_PYTHON%" -m signalpilot --report
if errorlevel 1 goto fail

goto end

:fail
echo.
echo SignalPilot could not show the report.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

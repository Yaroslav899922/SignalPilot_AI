@echo off
setlocal

call "%~dp0_ensure-local-install.bat"
if errorlevel 1 goto fail

"%SIGNALPILOT_PYTHON%" -m unittest discover -s tests
if errorlevel 1 goto fail

goto end

:fail
echo.
echo SignalPilot tests failed or could not start.

:end
echo.
if not "%SIGNALPILOT_NO_PAUSE%"=="1" pause

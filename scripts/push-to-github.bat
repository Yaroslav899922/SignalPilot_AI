@echo off
cd /d "%~dp0.."
echo.
echo Vidpravka onovlen SignalPilot na GitHub...
echo.
git push origin main
if errorlevel 1 goto fail
echo.
echo ===== GOTOVO! Vse na GitHub. Mozhna zakryty vikno. =====
goto end
:fail
echo.
echo Push ne vdavsya. Skopiyuy tekst vyshche i nadishly Claude.
:end
echo.
pause

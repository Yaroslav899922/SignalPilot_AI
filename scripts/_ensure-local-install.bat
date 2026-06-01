@echo off
cd /d "%~dp0.."

set "SIGNALPILOT_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%SIGNALPILOT_PYTHON%" (
    echo Creating local Python environment in .venv ...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

"%SIGNALPILOT_PYTHON%" -m pip show signalpilot >nul 2>nul
if errorlevel 1 (
    echo Installing SignalPilot into .venv ...
    "%SIGNALPILOT_PYTHON%" -m pip install -e .
    if errorlevel 1 exit /b 1
)

exit /b 0

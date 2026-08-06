@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment is missing. Run setup.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  echo [ERROR] .env is missing. Run setup.bat and set DISCORD_TOKEN.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m tracker
if errorlevel 1 pause

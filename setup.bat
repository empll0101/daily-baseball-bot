@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :error
if not exist ".env" copy ".env.example" ".env"
echo.
echo Setup completed. Edit .env and set DISCORD_TOKEN, then run run_bot.bat.
pause
exit /b 0

:error
echo.
echo Setup failed. Please copy the error messages above.
pause
exit /b 1

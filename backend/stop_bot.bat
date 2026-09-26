@echo off
REM Stop ICT Trading Bot on Windows
REM Usage: stop_bot.bat

cd /d "C:\Users\lenovo\trading-signal-app\backend"

REM Find and kill python process running trading_bot.py
for /f "tokens=2" %%i in ('tasklist ^| findstr "trading_bot.py"') do (
    taskkill /PID %%i /F
    echo Stopped bot process %%i
)

if errorlevel 1 (
    echo No trading_bot.py process found
)

echo Bot stopped.
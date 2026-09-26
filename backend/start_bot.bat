@echo off
REM Start ICT Trading Bot on Windows
REM Usage: start_bot.bat

cd /d "C:\Users\lenovo\trading-signal-app\backend"

REM Run bot in background
start /b python trading_bot.py > bot_service.log 2>&1

REM Get PID (Windows doesn't have easy PID tracking for background processes)
echo Bot started in background. Check bot_service.log for output.
echo To stop: run stop_bot.bat
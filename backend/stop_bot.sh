#!/bin/bash
# Stop ICT Trading Bot
# Usage: ./stop_bot.sh

cd /c/Users/lenovo/trading-signal-app/backend

if [ -f bot.pid ]; then
    PID=$(cat bot.pid)
    if kill -0 $PID 2>/dev/null; then
        kill $PID
        echo "Bot stopped (PID: $PID)"
    else
        echo "Bot not running (stale PID file)"
    fi
    rm -f bot.pid
else
    echo "No PID file found"
fi
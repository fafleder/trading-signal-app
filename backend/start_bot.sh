#!/bin/bash
# Start ICT Trading Bot as background service
# Usage: ./start_bot.sh

cd /c/Users/lenovo/trading-signal-app/backend

# Activate virtual environment if needed
# source venv/bin/activate

# Run bot
python trading_bot.py >> bot_service.log 2>&1 &

echo $! > bot.pid
echo "Bot started with PID $(cat bot.pid)"
#!/usr/bin/env python3
"""
Telegram notification sender for valid signals
"""
import json
import os
import sys
import requests

def send_notification():
    signals_file = 'trading-signal-app/backend/signals_output.json'
    
    if not os.path.exists(signals_file):
        return
    
    with open(signals_file) as f:
        signals = json.load(f)
    
    if not signals:
        return
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not bot_token or not chat_id:
        print('Telegram credentials not set')
        return
    
    message = '🎯 <b>Valid ICT Signals with Live Price Match</b>\n\n'
    for s in signals:
        message += f"<b>{s['asset']} {s['setup_type'].upper()} {s['direction'].upper()}</b>\n"
        message += f"Entry: {s['entry_price']:.5f} | SL: {s['stop_loss']:.5f} | TP1: {s['take_profit_1']:.5f}\n"
        message += f"R:R: {s['risk_reward']} | Conf: {s['confidence']:.0%}\n"
        message += f"Exp: {s['expiration_time_est']} EST ({s.get('kill_zone', 'N/A')})\n"
        if s.get('notes'):
            message += f"Note: {s['notes']}\n"
        message += '\n'
    
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    response = requests.post(url, json={
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    })
    print(f'Telegram sent: {response.status_code}')

if __name__ == '__main__':
    send_notification()
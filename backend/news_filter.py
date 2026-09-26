"""
News Calendar Filter for ICT Trading Bot
Fetches economic calendar and blocks trading around high-impact events
"""

import requests
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# Free economic calendar APIs
CALENDAR_APIS = {
    'forexfactory': 'https://nfs.faireconomy.media/ff_calendar_thisweek.json',
    'tradingeconomics': 'https://api.tradingeconomics.com/calendar?c=guest:guest',
    'investing': 'https://api.investing.com/api/financialdata/economiccalendar'
}

# High impact events that should block trading
HIGH_IMPACT_KEYWORDS = [
    'NFP', 'Non-Farm', 'Employment', 'Unemployment', 'CPI', 'Inflation',
    'FOMC', 'Fed Rate', 'Interest Rate', 'ECB Rate', 'BOE Rate', 'BOJ Rate',
    'GDP', 'Retail Sales', 'PMI', 'ISM', 'Central Bank', 'Monetary Policy',
    'Core PCE', 'PCE Price', 'Wage', 'Average Hourly Earnings'
]

MEDIUM_IMPACT_KEYWORDS = [
    'Durable Goods', 'Factory Orders', 'Trade Balance', 'Current Account',
    'Consumer Confidence', 'Business Confidence', 'Housing Starts',
    'Building Permits', 'Industrial Production', 'Capacity Utilization'
]

class NewsFilter:
    def __init__(self, config: Dict):
        self.config = config.get('news_filter', {})
        self.enabled = self.config.get('enabled', True)
        self.high_before = self.config.get('high_impact_minutes_before', 30)
        self.high_after = self.config.get('high_impact_minutes_after', 30)
        self.medium_before = self.config.get('medium_impact_minutes_before', 15)
        self.medium_after = self.config.get('medium_impact_minutes_after', 15)
        self.cached_events: List[Dict] = []
        self.last_fetch = None
        self.cache_duration = 3600  # 1 hour cache
        
    def fetch_calendar(self) -> List[Dict]:
        """Fetch economic calendar from free API"""
        try:
            # Use Forex Factory free calendar
            response = requests.get(CALENDAR_APIS['forexfactory'], timeout=10)
            if response.status_code == 200:
                events = response.json()
                logger.info(f"Fetched {len(events)} economic events")
                return events
        except Exception as e:
            logger.warning(f"Failed to fetch calendar: {e}")
        return []
    
    def parse_events(self, raw_events: List[Dict]) -> List[Dict]:
        """Parse and normalize events"""
        parsed = []
        for event in raw_events:
            try:
                # Forex Factory format
                event_time = datetime.fromisoformat(event.get('date', '').replace('Z', '+00:00'))
                currency = event.get('country', event.get('currency', 'USD'))
                title = event.get('title', event.get('event', ''))
                impact = event.get('impact', '').lower()
                
                # Determine impact level
                impact_level = 'low'
                if impact == 'high' or any(kw.lower() in title.lower() for kw in HIGH_IMPACT_KEYWORDS):
                    impact_level = 'high'
                elif impact == 'medium' or any(kw.lower() in title.lower() for kw in MEDIUM_IMPACT_KEYWORDS):
                    impact_level = 'medium'
                
                parsed.append({
                    'time': event_time,
                    'currency': currency,
                    'title': title,
                    'impact': impact_level,
                    'actual': event.get('actual', ''),
                    'forecast': event.get('forecast', ''),
                    'previous': event.get('previous', '')
                })
            except Exception as e:
                logger.debug(f"Event parse error: {e}")
                continue
        return parsed
    
    def update_calendar(self):
        """Update cached events"""
        if self.last_fetch and (datetime.now(timezone.utc) - self.last_fetch).seconds < self.cache_duration:
            return
        
        raw = self.fetch_calendar()
        self.cached_events = self.parse_events(raw)
        self.last_fetch = datetime.now(timezone.utc)
        logger.info(f"Calendar updated: {len(self.cached_events)} events")
    
    def is_blocked(self, symbol: str, now: datetime = None) -> tuple:
        """Check if trading should be blocked for a symbol"""
        if not self.enabled:
            return False, ""
        
        self.update_calendar()
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Map symbol to currency
        currency_map = {
            'XAUUSD': ['USD', 'XAU'],
            'NASDAQ': ['USD'],
            'USTEC': ['USD'],
            'EURUSD': ['EUR', 'USD'],
            'GBPUSD': ['GBP', 'USD'],
            'USDJPY': ['USD', 'JPY'],
            'AUDUSD': ['AUD', 'USD'],
            'USDCAD': ['USD', 'CAD'],
        }
        
        currencies = currency_map.get(symbol, [symbol[:3], symbol[3:]])
        
        for event in self.cached_events:
            if event['currency'] not in currencies:
                continue
            
            event_time = event['time']
            time_diff = (event_time - now).total_seconds() / 60  # minutes
            
            if event['impact'] == 'high':
                if -self.high_after <= time_diff <= self.high_before:
                    return True, f"HIGH IMPACT: {event['title']} in {abs(int(time_diff))} min"
            elif event['impact'] == 'medium':
                if -self.medium_after <= time_diff <= self.medium_before:
                    return True, f"MEDIUM IMPACT: {event['title']} in {abs(int(time_diff))} min"
        
        return False, ""
    
    def get_upcoming_events(self, hours: int = 24) -> List[Dict]:
        """Get upcoming events for display"""
        self.update_calendar()
        now = datetime.now(timezone.utc)
        upcoming = []
        for event in self.cached_events:
            time_diff = (event['time'] - now).total_seconds() / 3600
            if 0 <= time_diff <= hours:
                upcoming.append({
                    **event,
                    'hours_until': round(time_diff, 1)
                })
        return sorted(upcoming, key=lambda x: x['time'])


# Singleton instance
_news_filter = None

def get_news_filter(config: Dict = None) -> NewsFilter:
    global _news_filter
    if _news_filter is None:
        _news_filter = NewsFilter(config or {})
    return _news_filter
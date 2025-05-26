# Backend

See the main [README.md](../README.md) at the project root for setup, environment variables, and documentation. 

## Database Schema (Supabase)

### market_data
| Column     | Type    | Description                |
|------------|---------|----------------------------|
| id         | int     | Primary key (auto)         |
| timestamp  | string  | ISO datetime               |
| asset      | string  | e.g. XAUUSD, NASDAQ        |
| open       | float   | Open price                 |
| high       | float   | High price                 |
| low        | float   | Low price                  |
| close      | float   | Close price                |
| volume     | float   | Volume                     |

### trade_signals
| Column            | Type    | Description                |
|-------------------|---------|----------------------------|
| id                | int     | Primary key (auto)         |
| asset             | string  | e.g. XAUUSD, NASDAQ        |
| timeframe         | string  | e.g. 1h, 4h                |
| bias              | string  | bullish, bearish, neutral  |
| liquidity_zones   | string  | e.g. 1800-1820             |
| entry_price       | float   |                            |
| stop_loss         | float   |                            |
| take_profit       | float   |                            |
| invalidation_point| float   |                            |
| system            | string  | e.g. Turtle Soup           |
| timestamp         | string  | ISO datetime (optional)    |

### portfolio_metrics
| Column            | Type    | Description                |
|-------------------|---------|----------------------------|
| id                | int     | Primary key (auto)         |
| risk_reward_ratio | float   |                            |
| win_rate          | float   |                            |
| drawdown          | float   |                            | 
import numpy as np

class SMC:
    @staticmethod
    def liquidity(highs, lows, closes):
        # Dummy: return zones at recent highs/lows
        if not highs or not lows:
            return []
        return [
            {"zone": "liquidity_high", "price": max(highs[-20:])},
            {"zone": "liquidity_low", "price": min(lows[-20:])}
        ]

    @staticmethod
    def ob(highs, lows, closes):
        # Dummy: return last close as order block
        if not closes:
            return []
        return [{"price": closes[-1], "type": "order_block"}]

    @staticmethod
    def fvg(highs, lows, closes, volumes=None):
        # Dummy: return a fair value gap if last close is far from last high/low
        if not closes or not highs or not lows:
            return []
        gap = abs(closes[-1] - highs[-1]) > 0.01 * closes[-1] or abs(closes[-1] - lows[-1]) > 0.01 * closes[-1]
        if gap:
            return [{"zone": "discount" if closes[-1] < np.mean(closes[-10:]) else "premium", "price": closes[-1]}]
        return []

    @staticmethod
    def sessions(highs, lows, closes):
        # Dummy: return session info
        return ["London", "New York", "Asia"]

    @staticmethod
    def swing_highs_lows(highs, lows):
        # Dummy: alternate higher_high/lower_low
        swings = []
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                swings.append({"type": "higher_high", "price": highs[i]})
            else:
                swings.append({"type": "lower_low", "price": lows[i]})
        return swings if swings else [{"type": "higher_high", "price": highs[-1] if highs else 0}]

    @staticmethod
    def previous_high_low(highs, lows, periods):
        # Dummy: return previous highs/lows for given periods
        result = []
        for p in periods:
            if len(highs) >= p:
                result.append({"high": highs[-p], "low": lows[-p]})
        return result

smc = SMC() 
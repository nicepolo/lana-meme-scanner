"""
indicators.py — 計算技術指標
輸入：標準化 K 線 list
輸出：dict，包含 RSI、MACD、布林通道、MA、量能等
"""

import math
import statistics
from typing import List


def calc_indicators(klines_1h: list, klines_15m: list, klines_4h: list = None) -> dict:
    """計算多時間框架指標，回傳完整 dict"""
    result = {}

    # ── 1H 指標 ──────────────────────────────────────────────
    closes_1h = [k[4] for k in klines_1h]
    volumes_1h = [k[5] for k in klines_1h]

    result["price"]       = closes_1h[-1]
    result["rsi_1h"]      = calc_rsi(closes_1h, 14)
    result["macd_1h"]     = calc_macd(closes_1h)
    result["bb_1h"]       = calc_bollinger(closes_1h, 20, 2)
    result["ma7_1h"]      = sma(closes_1h, 7)
    result["ma25_1h"]     = sma(closes_1h, 25)
    result["ma99_1h"]     = sma(closes_1h, 99)
    result["vol_ratio_1h"] = volume_ratio(volumes_1h, 20)
    result["price_change_24h"] = price_change_pct(closes_1h, 24)  # 近 24 根 1h = 24h

    # ── 15M 指標 ─────────────────────────────────────────────
    closes_15m = [k[4] for k in klines_15m]
    volumes_15m = [k[5] for k in klines_15m]

    result["rsi_15m"]      = calc_rsi(closes_15m, 14)
    result["macd_15m"]     = calc_macd(closes_15m)
    result["bb_15m"]       = calc_bollinger(closes_15m, 20, 2)
    result["ma7_15m"]      = sma(closes_15m, 7)
    result["ma25_15m"]     = sma(closes_15m, 25)
    result["vol_ratio_15m"] = volume_ratio(volumes_15m, 20)

    # ── 4H 指標（若有）─────────────────────────────────────
    if klines_4h and len(klines_4h) >= 30:
        closes_4h = [k[4] for k in klines_4h]
        result["rsi_4h"]  = calc_rsi(closes_4h, 14)
        result["macd_4h"] = calc_macd(closes_4h)
        result["ma25_4h"] = sma(closes_4h, 25)
        result["trend_4h"] = "up" if closes_4h[-1] > sma(closes_4h, 25) else "down"
    else:
        result["rsi_4h"]  = None
        result["macd_4h"] = None
        result["ma25_4h"] = None
        result["trend_4h"] = "unknown"

    return result


# ── 計算函式 ──────────────────────────────────────────────────

def sma(closes: list, period: int) -> float:
    if len(closes) < period:
        return closes[-1]
    return sum(closes[-period:]) / period


def ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return closes[-1]
    k = 2 / (period + 1)
    ema_val = sum(closes[:period]) / period
    for price in closes[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_macd(closes: list, fast=12, slow=26, signal=9) -> dict:
    if len(closes) < slow + signal:
        return {"macd": 0, "signal": 0, "hist": 0, "cross": "none"}
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = ema_fast - ema_slow

    # 計算 signal line（MACD 的 EMA）
    macd_series = []
    for i in range(slow - 1, len(closes)):
        ef = ema(closes[:i+1], fast)
        es = ema(closes[:i+1], slow)
        macd_series.append(ef - es)

    if len(macd_series) < signal:
        sig_line = macd_line
    else:
        sig_line = ema(macd_series, signal)

    hist = macd_line - sig_line

    # 判斷金叉/死叉（最後兩根柱）
    cross = "none"
    if len(macd_series) >= 2:
        prev_hist = macd_series[-2] - sig_line
        if prev_hist < 0 and hist > 0:
            cross = "golden"   # 金叉
        elif prev_hist > 0 and hist < 0:
            cross = "death"    # 死叉

    return {
        "macd":   round(macd_line, 8),
        "signal": round(sig_line, 8),
        "hist":   round(hist, 8),
        "cross":  cross
    }


def calc_bollinger(closes: list, period: int = 20, std_dev: float = 2) -> dict:
    if len(closes) < period:
        price = closes[-1]
        return {"upper": price, "middle": price, "lower": price, "pct_b": 0.5, "position": "middle"}
    recent = closes[-period:]
    mid = sum(recent) / period
    std = statistics.stdev(recent)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    price = closes[-1]
    band_width = upper - lower
    pct_b = (price - lower) / band_width if band_width > 0 else 0.5

    if price > upper:
        position = "above_upper"
    elif price < lower:
        position = "below_lower"
    elif price > mid:
        position = "upper_half"
    else:
        position = "lower_half"

    return {
        "upper":    round(upper, 8),
        "middle":   round(mid, 8),
        "lower":    round(lower, 8),
        "pct_b":    round(pct_b, 3),
        "position": position
    }


def volume_ratio(volumes: list, period: int = 20) -> float:
    """現量 / 均量"""
    if len(volumes) < period + 1:
        return 1.0
    avg_vol = sum(volumes[-period-1:-1]) / period
    if avg_vol == 0:
        return 1.0
    return round(volumes[-1] / avg_vol, 2)


def price_change_pct(closes: list, periods: int = 24) -> float:
    if len(closes) < periods + 1:
        return 0.0
    old = closes[-periods - 1]
    new = closes[-1]
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 2)

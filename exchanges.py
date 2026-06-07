"""
exchanges.py — 抓取 Binance / Bybit / OKX 的 K 線資料
回傳格式統一：list of [open_time_ms, open, high, low, close, volume]
"""

import os
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

# Proxy 設定（若 Railway 區域被擋可改成 proxy）
PROXIES = {}

HEADERS = {"Content-Type": "application/json"}

# ── 交易所 interval 對應表 ──────────────────────────────────────
BINANCE_INTERVALS = {"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d"}
BYBIT_INTERVALS   = {"1","3","5","15","30","60","120","240","360","720","D","W","M"}
OKX_INTERVALS     = {"1m","3m","5m","15m","30m","1H","2H","4H","6H","12H","1D"}

INTERVAL_MAP = {
    "1m":  {"bybit": "1",   "okx": "1m"},
    "5m":  {"bybit": "5",   "okx": "5m"},
    "15m": {"bybit": "15",  "okx": "15m"},
    "30m": {"bybit": "30",  "okx": "30m"},
    "1h":  {"bybit": "60",  "okx": "1H"},
    "4h":  {"bybit": "240", "okx": "4H"},
    "1d":  {"bybit": "D",   "okx": "1D"},
}
# ───────────────────────────────────────────────────────────────


def get_all_klines(symbol: str, exchange: str, interval: str = "1h", limit: int = 100):
    """統一介面，回傳標準化 K 線 list"""
    exchange = exchange.lower()
    try:
        if exchange == "binance":
            return _binance_klines(symbol, interval, limit)
        elif exchange == "bybit":
            return _bybit_klines(symbol, interval, limit)
        elif exchange == "okx":
            return _okx_klines(symbol, interval, limit)
        else:
            log.warning(f"不支援的交易所: {exchange}")
            return []
    except Exception as e:
        log.error(f"[{exchange}] {symbol} {interval} K 線抓取失敗: {e}")
        return []


def _binance_klines(symbol: str, interval: str, limit: int):
    # 先試現貨
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
        r = requests.get(url, params=params, headers=HEADERS, proxies=PROXIES, timeout=10)
        r.raise_for_status()
        raw = r.json()
        if raw and isinstance(raw, list):
            return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                    for k in raw]
    except Exception:
        pass

    # 現貨沒有，改試合約（永續）
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
        r = requests.get(url, params=params, headers=HEADERS, proxies=PROXIES, timeout=10)
        r.raise_for_status()
        raw = r.json()
        if raw and isinstance(raw, list):
            return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                    for k in raw]
    except Exception:
        pass

    return []


def _bybit_klines(symbol: str, interval: str, limit: int):
    bybit_interval = INTERVAL_MAP.get(interval, {}).get("bybit", "60")
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": f"{symbol}USDT",
        "interval": bybit_interval,
        "limit": limit
    }
    r = requests.get(url, params=params, headers=HEADERS, proxies=PROXIES, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        log.warning(f"[Bybit] {symbol} 回應錯誤: {data.get('retMsg')}")
        return []
    raw = data["result"]["list"]
    # Bybit 回傳由新到舊，需反轉
    raw = list(reversed(raw))
    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
            for k in raw]


def _okx_klines(symbol: str, interval: str, limit: int):
    okx_bar = INTERVAL_MAP.get(interval, {}).get("okx", "1H")
    url = "https://www.okx.com/api/v5/market/candles"
    params = {
        "instId": f"{symbol}-USDT",
        "bar": okx_bar,
        "limit": str(limit)
    }
    r = requests.get(url, params=params, headers=HEADERS, proxies=PROXIES, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "0":
        log.warning(f"[OKX] {symbol} 回應錯誤: {data.get('msg')}")
        return []
    raw = data["data"]
    raw = list(reversed(raw))
    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
            for k in raw]


def get_current_price(symbol: str, exchange: str) -> float:
    """快速抓現價"""
    try:
        exchange = exchange.lower()
        if exchange == "binance":
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
            return float(requests.get(url, timeout=5).json()["price"])
        elif exchange == "bybit":
            url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}USDT"
            data = requests.get(url, timeout=5).json()
            return float(data["result"]["list"][0]["lastPrice"])
        elif exchange == "okx":
            url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}-USDT"
            data = requests.get(url, timeout=5).json()
            return float(data["data"][0]["last"])
    except Exception as e:
        log.error(f"[{exchange}] {symbol} 現價抓取失敗: {e}")
        return 0.0

"""
LANA Meme Scanner v1.0
土狗幣 + LUNA 多空 AI 分析掃描模組
支援 Binance / Bybit / OKX
"""

import os
import time
import json
import logging
import schedule
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv

from exchanges import get_all_klines
from indicators import calc_indicators
from ai_analysis import analyze_coin
from notify import send_telegram

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── 監控幣種設定 ──────────────────────────────────────────────
WATCH_LIST = [
    # symbol,       exchanges（OKX/Bybit 優先，避開 Binance 地區封鎖）
    ("LUNA",   ["okx", "bybit"]),
    ("LUNC",   ["okx"]),
    ("DOGE",   ["okx", "bybit"]),
    ("SHIB",   ["okx", "bybit"]),
    ("PEPE",   ["okx", "bybit"]),
    ("FLOKI",  ["okx", "bybit"]),
    ("BONK",   ["okx"]),
    ("WIF",    ["okx", "bybit"]),
    ("NEIRO",  ["okx"]),
    ("MEME",   ["okx"]),
]

SCAN_INTERVAL_MIN = int(os.getenv("MEME_SCAN_INTERVAL_MIN", "15"))
MIN_SCORE_TO_ALERT = int(os.getenv("MIN_SCORE_TO_ALERT", "60"))  # 0-100，低於此分不推播
# ──────────────────────────────────────────────────────────────


def scan_once():
    log.info("═══ LANA Meme Scanner 開始掃描 ═══")
    results = []

    for symbol, exchanges in WATCH_LIST:
        for exchange in exchanges:
            try:
                klines_1h  = get_all_klines(symbol, exchange, interval="1h",  limit=100)
                klines_15m = get_all_klines(symbol, exchange, interval="15m", limit=100)
                klines_4h  = get_all_klines(symbol, exchange, interval="4h",  limit=50)

                if not klines_1h or not klines_15m:
                    log.warning(f"[{exchange}] {symbol} K 線資料不足，跳過")
                    continue

                indicators = calc_indicators(klines_1h, klines_15m, klines_4h)
                analysis   = analyze_coin(symbol, exchange, indicators)

                if analysis and analysis.get("score", 0) >= MIN_SCORE_TO_ALERT:
                    results.append(analysis)
                    log.info(f"✅ [{exchange}] {symbol} 分數 {analysis['score']} → 加入推播")
                else:
                    log.info(f"[{exchange}] {symbol} 分數不足或無訊號，略過")

            except Exception as e:
                log.error(f"[{exchange}] {symbol} 掃描出錯: {e}")

    if results:
        # 依分數排序，最強訊號排前面
        results.sort(key=lambda x: x["score"], reverse=True)
        send_telegram(results)
        log.info(f"📨 推播 {len(results)} 個訊號")
    else:
        log.info("本輪無達標訊號，不推播")

    log.info("═══ 掃描完畢 ═══\n")


def run_scheduler():
    schedule.every(SCAN_INTERVAL_MIN).minutes.do(scan_once)
    log.info(f"⏰ 排程啟動，每 {SCAN_INTERVAL_MIN} 分鐘掃描一次")
    # 啟動時先掃一次
    scan_once()
    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    run_scheduler()

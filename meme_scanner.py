"""
LANA Meme Scanner v1.1
土狗幣 + LUNA 多空 AI 分析掃描模組
支援 OKX | Flask Web API + 背景掃描
"""

import os, time, json, logging, threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
from flask_cors import CORS
import schedule
from dotenv import load_dotenv

from exchanges import get_all_klines
from indicators import calc_indicators
from ai_analysis import analyze_coin
from notify import send_telegram

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
# ── 設定 ──────────────────────────────────────────────────────
WATCH_LIST = [
    ("LUNA",   ["okx"]),
    ("LUNC",   ["okx"]),
    ("DOGE",   ["okx"]),
    ("SHIB",   ["okx"]),
    ("PEPE",   ["okx"]),
    ("FLOKI",  ["okx"]),
    ("BONK",   ["okx"]),
    ("WIF",    ["okx"]),
    ("NEIRO",  ["okx"]),
    ("MEME",   ["okx"]),
    ("POPCAT", ["okx"]),
    ("MEW",    ["okx"]),
    ("BRETT",  ["okx"]),
    ("MOG",    ["okx"]),
    ("TURBO",  ["okx"]),
]
SCAN_INTERVAL_MIN  = int(os.getenv("MEME_SCAN_INTERVAL_MIN", "15"))
MIN_SCORE_TO_ALERT = int(os.getenv("MIN_SCORE_TO_ALERT", "60"))
PORT = int(os.getenv("PORT", "8080"))
TZ_TAIPEI = timezone(timedelta(hours=8))

# ── 全域快取 ──────────────────────────────────────────────────
_cache = {
    "signals": [],
    "all_results": [],   # 所有幣，不限分數
    "last_update": None,
    "scan_count": 0,
}
_lock = threading.Lock()

# ── API 端點 ──────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "LANA Meme Scanner v1.1"})

@app.route("/api/meme_signals")
def meme_signals():
    with _lock:
        return jsonify({
            "signals":     _cache["signals"],
            "all_results": _cache["all_results"],
            "last_update": _cache["last_update"],
            "scan_count":  _cache["scan_count"],
            "watch_count": len(WATCH_LIST),
        })

@app.route("/api/ai_analyze", methods=["POST"])
def ai_analyze():
    """讓主網頁呼叫，分析任意幣種的多空方向"""
    from flask import request as freq
    body = freq.get_json() or {}
    symbol = body.get("symbol", "").upper().strip()
    price  = float(body.get("price", 0))
    change = float(body.get("change_24h", 0))

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    try:
        # 抓 OKX K 線
        klines_1h  = get_all_klines(symbol, "okx", interval="1h",  limit=100)
        klines_15m = get_all_klines(symbol, "okx", interval="15m", limit=100)
        klines_4h  = get_all_klines(symbol, "okx", interval="4h",  limit=50)

        if klines_1h and klines_15m:
            indicators = calc_indicators(klines_1h, klines_15m, klines_4h)
            result = analyze_coin(symbol, "okx", indicators)
        else:
            # OKX 沒有，自動改用 Binance
            log.info(f"OKX 無資料，改用 Binance 抓 {symbol}")
            klines_1h  = get_all_klines(symbol, "binance", interval="1h",  limit=100)
            klines_15m = get_all_klines(symbol, "binance", interval="15m", limit=100)
            klines_4h  = get_all_klines(symbol, "binance", interval="4h",  limit=50)
            if klines_1h and klines_15m:
                indicators = calc_indicators(klines_1h, klines_15m, klines_4h)
                result = analyze_coin(symbol, "binance", indicators)
            else:
                # 兩家都沒有，改用 Bybit
                log.info(f"Binance 也無資料，改用 Bybit 抓 {symbol}")
                klines_1h  = get_all_klines(symbol, "bybit", interval="1h",  limit=100)
                klines_15m = get_all_klines(symbol, "bybit", interval="15m", limit=100)
                klines_4h  = get_all_klines(symbol, "bybit", interval="4h",  limit=50)
                if klines_1h and klines_15m:
                    indicators = calc_indicators(klines_1h, klines_15m, klines_4h)
                    result = analyze_coin(symbol, "bybit", indicators)
                else:
                    result = {
                        "symbol": symbol, "exchange": "N/A",
                        "direction": "WATCH", "score": 40,
                        "confidence": "低", "summary": "三大交易所均無資料",
                        "reason": "此幣可能為純鏈上幣，未在主流交易所上架，建議透過 DEX 查詢",
                        "entry_zone": "N/A", "stop_loss": "N/A",
                        "target_1": "N/A", "target_2": "N/A",
                        "timeframe": "N/A", "risk_note": "鏈上幣風險極高，務必先查合約",
                        "price": price, "change_24h": change,
                        "vol_ratio": 1.0, "rsi_1h": 50
                    }

        if not result:
            result = {"direction": "WATCH", "score": 40, "summary": "無明確訊號", "reason": "指標中性"}

        return jsonify(result)

    except Exception as e:
        log.error(f"ai_analyze [{symbol}] 錯誤: {e}")
        return jsonify({"error": str(e)}), 500



    with _lock:
        return jsonify({
            "status": "ok",
            "last_update": _cache["last_update"],
            "signal_count": len(_cache["signals"]),
        })

# ── 掃描邏輯 ──────────────────────────────────────────────────

def scan_once():
    log.info("═══ LANA Meme Scanner 開始掃描 ═══")
    results = []
    all_res  = []

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

                if analysis:
                    all_res.append(analysis)
                    if analysis.get("score", 0) >= MIN_SCORE_TO_ALERT:
                        results.append(analysis)
                        log.info(f"✅ [{exchange}] {symbol} 分數 {analysis['score']} → 達標")
                    else:
                        log.info(f"[{exchange}] {symbol} 分數 {analysis.get('score',0)} 不足，略過推播")

            except Exception as e:
                log.error(f"[{exchange}] {symbol} 掃描出錯: {e}")

    now_str = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M")

    with _lock:
        _cache["signals"]     = sorted(results,  key=lambda x: x["score"], reverse=True)
        _cache["all_results"] = sorted(all_res,  key=lambda x: x["score"], reverse=True)
        _cache["last_update"] = now_str
        _cache["scan_count"] += 1

    if results:
        send_telegram(results)
        log.info(f"📨 推播 {len(results)} 個訊號")
    else:
        log.info("本輪無達標訊號，不推播")

    log.info("═══ 掃描完畢 ═══\n")


def run_scheduler():
    schedule.every(SCAN_INTERVAL_MIN).minutes.do(scan_once)
    log.info(f"⏰ 排程啟動，每 {SCAN_INTERVAL_MIN} 分鐘掃描一次")
    scan_once()
    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    # 背景啟動掃描排程
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    # 啟動 Flask Web 服務
    log.info(f"🌐 Web API 啟動 port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)

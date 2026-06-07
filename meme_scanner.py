"""
LANA Meme Scanner v2.0
全市場動態掃描 - 自動找當下最熱幣種
"""

import os, time, json, logging, threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request as freq
from flask_cors import CORS
import requests
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

# ── 設定 ──────────────────────────────────────────────
SCAN_INTERVAL_MIN  = int(os.getenv("MEME_SCAN_INTERVAL_MIN", "15"))
MIN_SCORE_TO_ALERT = int(os.getenv("MIN_SCORE_TO_ALERT", "60"))
MIN_CHANGE_PCT     = float(os.getenv("MIN_CHANGE_PCT", "5"))
MIN_VOLUME_USDT    = float(os.getenv("MIN_VOLUME_USDT", "500000"))
MAX_COINS_TO_SCAN  = int(os.getenv("MAX_COINS_TO_SCAN", "20"))
PORT = int(os.getenv("PORT", "8080"))
TZ_TAIPEI = timezone(timedelta(hours=8))

# 固定加入的重點幣（即使漲幅不足也要掃）
CORE_COINS = ["DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "NEIRO", "POPCAT"]

# ── 全域快取 ──────────────────────────────────────────
_cache = {
    "signals": [],
    "all_results": [],
    "last_update": None,
    "scan_count": 0,
    "hot_coins": [],
}
_lock = threading.Lock()

# ── 掃描 OKX 全市場找熱門幣 ───────────────────────────
def fetch_hot_coins_okx():
    """從 OKX 抓取 24h 漲幅最大、成交量最高的幣種"""
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
        
        candidates = []
        for t in data:
            inst_id = t.get("instId", "")
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            symbol = inst_id.replace("-USDT-SWAP", "")
            
            try:
                chg = float(t.get("sodUtc8", 0))  # 今日漲跌幅
                vol = float(t.get("volCcy24h", 0))  # 24h成交量
                price = float(t.get("last", 0))
            except:
                continue
            
            if vol < MIN_VOLUME_USDT:
                continue
                
            candidates.append({
                "symbol": symbol,
                "change": round(chg * 100, 2),
                "volume": round(vol),
                "price": price,
            })
        
        # 按漲幅排序，取前20
        hot = sorted(candidates, key=lambda x: abs(x["change"]), reverse=True)
        hot = [c for c in hot if abs(c["change"]) >= MIN_CHANGE_PCT]
        
        # 合併核心幣
        hot_symbols = [c["symbol"] for c in hot[:MAX_COINS_TO_SCAN]]
        for coin in CORE_COINS:
            if coin not in hot_symbols:
                hot_symbols.append(coin)
        
        log.info(f"🔍 發現 {len(hot_symbols)} 個待掃描幣種: {', '.join(hot_symbols[:10])}...")
        return hot_symbols
        
    except Exception as e:
        log.error(f"抓取熱門幣失敗: {e}")
        return CORE_COINS

# ── 掃描邏輯 ──────────────────────────────────────────
def scan_once():
    log.info("═══ LANA Meme Scanner v2.0 開始掃描 ═══")
    
    hot_coins = fetch_hot_coins_okx()
    results = []
    all_res = []

    for symbol in hot_coins:
        try:
            klines_1h  = get_all_klines(symbol, "okx", interval="1h",  limit=100)
            klines_15m = get_all_klines(symbol, "okx", interval="15m", limit=100)
            klines_4h  = get_all_klines(symbol, "okx", interval="4h",  limit=50)

            if not klines_1h or not klines_15m:
                log.warning(f"[okx] {symbol} K線資料不足，跳過")
                continue

            indicators = calc_indicators(klines_1h, klines_15m, klines_4h)
            analysis   = analyze_coin(symbol, "okx", indicators)

            if analysis:
                all_res.append(analysis)
                score = analysis.get("score", 0)
                if score >= MIN_SCORE_TO_ALERT:
                    results.append(analysis)
                    log.info(f"✅ {symbol} 分數 {score} → 達標推播")
                else:
                    log.info(f"[okx] {symbol} 分數 {score} 不足，略過")

        except Exception as e:
            log.error(f"[okx] {symbol} 掃描出錯: {e}")

    now_str = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M")

    with _lock:
        _cache["signals"]     = sorted(results, key=lambda x: x["score"], reverse=True)
        _cache["all_results"] = sorted(all_res, key=lambda x: x["score"], reverse=True)
        _cache["last_update"] = now_str
        _cache["scan_count"] += 1
        _cache["hot_coins"]   = hot_coins

    if results:
        send_telegram(results)
        log.info(f"📨 推播 {len(results)} 個訊號")
    else:
        log.info("本輪無達標訊號，不推播")

    log.info("═══ 掃描完畢 ═══\n")

# ── API 端點 ──────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "LANA Meme Scanner v2.0"})

@app.route("/api/meme_signals")
def meme_signals():
    with _lock:
        return jsonify({
            "signals":     _cache["signals"],
            "all_results": _cache["all_results"],
            "last_update": _cache["last_update"],
            "scan_count":  _cache["scan_count"],
            "hot_coins":   _cache["hot_coins"],
        })

@app.route("/api/ai_analyze", methods=["POST"])
def ai_analyze():
    body = freq.get_json() or {}
    symbol = body.get("symbol", "").upper().strip()
    price  = float(body.get("price", 0))
    change = float(body.get("change_24h", 0))

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    try:
        klines_1h  = get_all_klines(symbol, "okx", interval="1h",  limit=100)
        klines_15m = get_all_klines(symbol, "okx", interval="15m", limit=100)
        klines_4h  = get_all_klines(symbol, "okx", interval="4h",  limit=50)

        if klines_1h and klines_15m:
            indicators = calc_indicators(klines_1h, klines_15m, klines_4h)
            result = analyze_coin(symbol, "okx", indicators)
        else:
            result = {
                "symbol": symbol, "exchange": "N/A",
                "direction": "WATCH", "score": 40,
                "confidence": "低", "summary": "無資料",
                "reason": "OKX 無此幣種資料",
                "entry_zone": "N/A", "stop_loss": "N/A",
                "target_1": "N/A", "target_2": "N/A",
                "price": price, "change_24h": change,
            }

        return jsonify(result or {"direction": "WATCH", "score": 40})

    except Exception as e:
        log.error(f"ai_analyze [{symbol}] 錯誤: {e}")
        return jsonify({"error": str(e)}), 500

def run_scheduler():
    schedule.every(SCAN_INTERVAL_MIN).minutes.do(scan_once)
    log.info(f"⏰ 排程啟動，每 {SCAN_INTERVAL_MIN} 分鐘掃描一次")
    scan_once()
    while True:
        schedule.run_pending()
        time.sleep(10)

if __name__ == "__main__":
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    log.info(f"🌐 Web API 啟動 port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)

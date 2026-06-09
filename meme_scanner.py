"""
LANA Meme Scanner v4.1 - Flask API + 背景排程
- /api/meme_signals  → 前端土狗 tab 呼叫
- /api/health        → 健康檢查
- 每15分鐘背景掃描一次，結果存記憶體
"""
import os, logging, requests, threading, time, json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from exchanges import get_all_klines
from indicators import calc_indicators
from ai_analysis import analyze_coin
from notify import send_telegram

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MIN_SCORE   = int(os.getenv("MIN_SCORE_TO_ALERT", "76"))
MIN_CHANGE  = float(os.getenv("MIN_CHANGE_PCT", "3"))
MIN_VOL     = float(os.getenv("MIN_VOLUME_USDT", "500000"))
MAX_COINS   = int(os.getenv("MAX_COINS_TO_SCAN", "50"))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_MIN", "15"))

MAJORS  = {"BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","DOT","MATIC","LINK","UNI"}
STABLES = {"USDT","USDC","BUSD","FDUSD","DAI","TUSD"}

FUNDING_EXTREME = 0.0005
FUNDING_STRONG  = 0.001

# ── 記憶體快取 ──────────────────────────────────────────────
_cache = {
    "signals":    [],       # 本輪所有分析結果（不限分數）
    "top_signals": [],      # 達標訊號（score >= MIN_SCORE）
    "last_scan":  None,
    "scan_count": 0,
}
_cache_lock = threading.Lock()

# 去重：記錄每顆幣最後推送的 timestamp，冷卻期內不重複推
_last_alerted = {}  # {symbol: timestamp}
_last_alerted_time = 0

# ── Flask ────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

@app.route("/api/meme_signals")
def api_meme_signals():
    with _cache_lock:
        return jsonify({
            "signals":    _cache["signals"],
            "last_scan":  _cache["last_scan"],
            "scan_count": _cache["scan_count"],
        })

@app.route("/api/health")
def api_health():
    with _cache_lock:
        return jsonify({
            "status": "ok",
            "last_scan": _cache["last_scan"],
            "scan_count": _cache["scan_count"],
            "signal_count": len(_cache["signals"]),
        })

@app.route("/")
def index():
    return "LANA Meme Scanner v4.1 OK"

# ── 掃描邏輯（原 main）────────────────────────────────────────

def fetch_funding_rates() -> dict:
    rates = {}
    try:
        r = requests.get("https://www.okx.com/api/v5/public/funding-rate?instType=SWAP", timeout=10)
        for item in r.json().get("data", []):
            inst = item.get("instId", "")
            if inst.endswith("-USDT-SWAP"):
                coin = inst.replace("-USDT-SWAP", "")
                try:
                    rates[coin] = float(item.get("fundingRate", 0))
                except:
                    pass
        log.info(f"資金費率抓取完成，共 {len(rates)} 個幣")
    except Exception as e:
        log.error(f"資金費率抓取失敗: {e}")
    return rates


def fetch_okx() -> list:
    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=10)
        out = []
        for t in r.json().get("data", []):
            inst = t.get("instId", "")
            if not inst.endswith("-USDT-SWAP"):
                continue
            coin = inst.replace("-USDT-SWAP", "")
            if coin in STABLES:
                continue
            try:
                chg = float(t.get("sodUtc8", 0)) * 100
                vol = float(t.get("volCcy24h", 0))
            except:
                continue
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                out.append((coin, abs(chg), "okx"))
        log.info(f"OKX 找到 {len(out)} 個候選幣")
        return out
    except Exception as e:
        log.error(f"OKX 抓取失敗: {e}")
        return []


def fetch_binance() -> list:
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10)
        out = []
        for t in r.json():
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            coin = sym[:-4]
            if coin in STABLES:
                continue
            chg = float(t.get("priceChangePercent", 0))
            vol = float(t.get("quoteVolume", 0))
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                out.append((coin, abs(chg), "binance"))
        log.info(f"Binance 找到 {len(out)} 個候選幣")
        return out
    except Exception as e:
        log.error(f"Binance 抓取失敗: {e}")
        return []


def fetch_bybit() -> list:
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=10)
        out = []
        for t in r.json().get("result", {}).get("list", []):
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            coin = sym[:-4]
            if coin in STABLES:
                continue
            try:
                chg = float(t.get("price24hPcnt", 0)) * 100
                vol = float(t.get("turnover24h", 0))
            except:
                continue
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                out.append((coin, abs(chg), "bybit"))
        log.info(f"Bybit 找到 {len(out)} 個候選幣")
        return out
    except Exception as e:
        log.error(f"Bybit 抓取失敗: {e}")
        return []


def get_best_candidates(funding_rates: dict) -> list:
    all_coins = fetch_okx() + fetch_binance() + fetch_bybit()
    best = {}
    for coin, chg, exchange in all_coins:
        if coin not in best or chg > best[coin][0]:
            best[coin] = (chg, exchange)
    for coin, rate in funding_rates.items():
        if abs(rate) >= FUNDING_EXTREME and coin not in STABLES:
            if coin not in best:
                best[coin] = (0, "okx")
    def sort_key(item):
        coin, (chg, _) = item
        fr = abs(funding_rates.get(coin, 0))
        fr_score = 2 if fr >= FUNDING_STRONG else 1 if fr >= FUNDING_EXTREME else 0
        return (fr_score, chg)
    sorted_coins = sorted(best.items(), key=sort_key, reverse=True)
    result = [(coin, exchange) for coin, (chg, exchange) in sorted_coins[:MAX_COINS]]
    log.info(f"最終掃描 {len(result)} 個幣種")
    return result


def run_scan():
    log.info("═══ LANA Meme Scanner v4.1 開始掃描 ═══")
    funding_rates = fetch_funding_rates()
    candidates = get_best_candidates(funding_rates)
    all_results = []
    top_signals = []

    for coin, exchange in candidates:
        try:
            k1h  = get_all_klines(coin, exchange, "1h",  100)
            k15m = get_all_klines(coin, exchange, "15m", 100)
            k4h  = get_all_klines(coin, exchange, "4h",  50)
            if not k1h or not k15m:
                log.warning(f"[{exchange}] {coin} 無資料，跳過")
                continue
            ind = calc_indicators(k1h, k15m, k4h)
            ind["funding_rate"] = funding_rates.get(coin, 0)
            res = analyze_coin(coin, exchange, ind)
            if not res:
                continue

            score     = res.get("score", 0)
            direction = res.get("direction", "WATCH")
            fr        = funding_rates.get(coin, 0)

            if coin in MAJORS:
                rsi_1h = ind.get("rsi_1h", 50)
                if not (abs(fr) >= FUNDING_EXTREME or rsi_1h >= 72 or rsi_1h <= 28):
                    log.info(f"[{exchange}] {coin} 主流幣條件不足（FR:{fr:.4f} RSI:{rsi_1h:.0f}），跳過")
                    continue

            res["funding_rate"] = fr
            res["is_major"]     = coin in MAJORS
            res["price"]        = ind.get("price", 0)
            res["change_24h"]   = ind.get("change_24h", ind.get("price_change_24h", 0))
            res["vol_ratio"]    = ind.get("vol_ratio_1h", ind.get("vol_ratio"))
            res["rsi_1h"]       = ind.get("rsi_1h", 50)

            p = res["price"]
            def _fix_price(val, default):
                try:
                    v = float(val)
                    return v if v > 0 else default
                except:
                    return default

            if p > 0:
                if direction == "SHORT":
                    res["stop_loss"] = _fix_price(res.get("stop_loss"), round(p * 1.03, 4))
                    res["target_1"]  = _fix_price(res.get("target_1"),  round(p * 0.96, 4))
                    res["target_2"]  = _fix_price(res.get("target_2"),  round(p * 0.92, 4))
                else:
                    res["stop_loss"] = _fix_price(res.get("stop_loss"), round(p * 0.97, 4))
                    res["target_1"]  = _fix_price(res.get("target_1"),  round(p * 1.04, 4))
                    res["target_2"]  = _fix_price(res.get("target_2"),  round(p * 1.08, 4))

            log.info(f"[{exchange}] {coin} → {direction} {score}分 FR:{fr:.4f}")
            all_results.append(res)

            # ── 硬性排除條件（雙向）──
            # 注意：不用 or 預設值，避免 0 被轉成 1.0
            vol_ratio = res.get("vol_ratio")
            vol_ratio = float(vol_ratio) if vol_ratio is not None else None
            chg_24h   = res.get("change_24h", 0)
            chg_24h   = float(chg_24h) if chg_24h is not None else 0.0
            rsi_val   = res.get("rsi_1h", 50)
            rsi_val   = float(rsi_val) if rsi_val is not None else 50.0
            skip = False

            # 量能不足：多空都排除（vol_ratio 是 None 代表資料缺失也排除）
            if vol_ratio is None or vol_ratio < 0.8:
                log.info(f"[排除] {coin} 量能{vol_ratio}x 不足（門檻0.8x）")
                skip = True

            if not skip and direction == "LONG":
                # 做多：需要上漲動能
                if chg_24h < 1.5:
                    log.info(f"[排除] {coin} 做多但24H漲幅{chg_24h:.1f}%不足（門檻+1.5%）")
                    skip = True
                elif rsi_val > 75:
                    log.info(f"[排除] {coin} 做多但RSI={rsi_val:.0f}超買（門檻75）")
                    skip = True

            if not skip and direction == "SHORT":
                # 做空：需要下跌動能
                if chg_24h > -1.5:
                    log.info(f"[排除] {coin} 做空但24H漲幅{chg_24h:.1f}%下跌動能不足（門檻-1.5%）")
                    skip = True
                elif rsi_val < 28:
                    log.info(f"[排除] {coin} 做空但RSI={rsi_val:.0f}超賣避免追空")
                    skip = True

            if not skip and score >= MIN_SCORE and direction in ("LONG", "SHORT"):
                top_signals.append(res)

        except Exception as e:
            log.error(f"[{exchange}] {coin} 出錯: {e}")

    # 排序
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 更新快取
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    with _cache_lock:
        _cache["signals"]     = all_results
        _cache["top_signals"] = top_signals
        _cache["last_scan"]   = now_str
        _cache["scan_count"] += 1

    # 推 Telegram（按分數高到低排序，本輪去重）
    global _last_alerted, _last_alerted_time
    now_ts = time.time()
    cooldown = SCAN_INTERVAL * 60 * 2
    top_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 本輪去重：symbol 只推一次
    seen = set()
    deduped = []
    for s in top_signals:
        sym = s.get("symbol")
        if sym not in seen:
            seen.add(sym)
            deduped.append(s)

    # 跨輪去重：冷卻期內不重複推
    new_signals = []
    for s in deduped:
        sym = s.get("symbol")
        last_t = _last_alerted.get(sym, 0)
        if now_ts - last_t >= cooldown:
            new_signals.append(s)

    if new_signals:
        # 跨 process 去重：查 Telegram 最後一條訊息時間
        import requests as _req, hashlib
        fingerprint = hashlib.md5(
            ",".join(f"{s.get('symbol')}:{s.get('score')}" for s in new_signals).encode()
        ).hexdigest()[:12]
        try:
            r = _req.get(
                f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN','')}/getUpdates",
                params={"limit": 5, "offset": -5},
                timeout=8
            )
            for update in r.json().get("result", []):
                msg = update.get("message", {})
                msg_text = msg.get("text", "")
                msg_time = msg.get("date", 0)
                # 如果 3 分鐘內有相同指紋的訊息，跳過
                if fingerprint in msg_text and now_ts - msg_time < 180:
                    log.warning(f"⛔ TG 已有相同訊號（指紋:{fingerprint}），略過重複推送")
                    new_signals = []
                    break
        except Exception as e:
            log.warning(f"TG 去重查詢失敗: {e}")

        if new_signals:
            send_telegram(new_signals)
            for s in new_signals:
                _last_alerted[s.get("symbol")] = now_ts
            _last_alerted_time = now_ts
            log.info(f"📨 推播 {len(new_signals)} 個新訊號")
    else:
        log.info("本輪無新達標訊號（或全部在冷卻期）")

    log.info(f"═══ 掃描完畢，共分析 {len(all_results)} 個幣 ═══")


def background_scheduler():
    """
    台北時間 03:00-07:00 → 每 120 分鐘跑一次
    其他時段 → 每 SCAN_INTERVAL 分鐘跑一次（預設 15 分鐘）
    等到下一個整15分鐘才跑第一次，避免重部署連續觸發
    """
    from datetime import datetime, timezone, timedelta
    TZ_TAIPEI = timezone(timedelta(hours=8))

    # 等到下一個 :00/:15/:30/:45 再跑
    now = datetime.now(TZ_TAIPEI)
    m = now.minute
    s = now.second
    if m < 15:   wait = (15 - m) * 60 - s
    elif m < 30: wait = (30 - m) * 60 - s
    elif m < 45: wait = (45 - m) * 60 - s
    else:        wait = (60 - m) * 60 - s
    wait = max(60, wait)  # 至少等 60 秒
    log.info(f"排程等待 {wait//60}分{wait%60}秒 後首次掃描（台北 {now.strftime('%H:%M')}）")
    time.sleep(wait)
    run_scan()

    while True:
        now_tpe = datetime.now(TZ_TAIPEI)
        hour = now_tpe.hour
        if 3 <= hour < 7:
            interval_min = 120
        else:
            interval_min = SCAN_INTERVAL
        log.info(f"下次掃描於 {interval_min} 分鐘後（台北 {now_tpe.strftime('%H:%M')}）")
        time.sleep(interval_min * 60)
        run_scan()


if __name__ == "__main__":
    # Railway private network 要固定 port 才能被其他服務呼叫
    port = 8080
    # 背景排程
    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()
    # Flask 主程式
    app.run(host="0.0.0.0", port=port, threaded=True)

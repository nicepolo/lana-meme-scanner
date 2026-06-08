"""
LANA Meme Scanner v2.1 - Pure Cron Job
"""
import os, logging, requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from exchanges import get_all_klines
from indicators import calc_indicators
from ai_analysis import analyze_coin
from notify import send_telegram

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MIN_SCORE = int(os.getenv("MIN_SCORE_TO_ALERT", "55"))
MIN_CHANGE = float(os.getenv("MIN_CHANGE_PCT", "3"))
MIN_VOL = float(os.getenv("MIN_VOLUME_USDT", "500000"))
MAX_COINS = int(os.getenv("MAX_COINS_TO_SCAN", "25"))
CORE = ["DOGE","SHIB","PEPE","BONK","WIF","FLOKI","NEIRO"]
TZ = timezone(timedelta(hours=8))

def fetch_hot_coins():
    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=10)
        coins = []
        for t in r.json().get("data", []):
            inst = t.get("instId","")
            if not inst.endswith("-USDT-SWAP"):
                continue
            sym = inst.replace("-USDT-SWAP","")
            try:
                chg = float(t.get("sodUtc8", 0)) * 100
                vol = float(t.get("volCcy24h", 0))
            except:
                continue
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                coins.append((sym, abs(chg)))
        coins.sort(key=lambda x: x[1], reverse=True)
        hot = [c[0] for c in coins[:MAX_COINS]]
        for c in CORE:
            if c not in hot:
                hot.append(c)
        log.info(f"掃描幣種({len(hot)}): {', '.join(hot[:10])}...")
        return hot
    except Exception as e:
        log.error(f"抓熱門幣失敗: {e}")
        return CORE

def main():
    log.info("═══ LANA Meme Scanner 開始 ═══")
    hot = fetch_hot_coins()
    signals = []
    for sym in hot:
        try:
            k1h  = get_all_klines(sym, "okx", "1h",  100)
            k15m = get_all_klines(sym, "okx", "15m", 100)
            k4h  = get_all_klines(sym, "okx", "4h",  50)
            if not k1h or not k15m:
                continue
            ind = calc_indicators(k1h, k15m, k4h)
            res = analyze_coin(sym, "okx", ind)
            if res:
                score = res.get("score", 0)
                log.info(f"{sym} → {res.get('direction')} {score}分")
                if score >= MIN_SCORE:
                    signals.append(res)
        except Exception as e:
            log.error(f"{sym} 出錯: {e}")

    if signals:
        signals.sort(key=lambda x: x["score"], reverse=True)
        send_telegram(signals)
        log.info(f"📨 推播 {len(signals)} 個訊號")
    else:
        log.info("本輪無達標訊號")
    log.info("═══ 掃描完畢 ═══")

if __name__ == "__main__":
    main()

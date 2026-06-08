"""
LANA Meme Scanner v3.0 - 三大交易所全市場掃描
Binance + OKX + Bybit
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

MIN_SCORE  = int(os.getenv("MIN_SCORE_TO_ALERT", "55"))
MIN_CHANGE = float(os.getenv("MIN_CHANGE_PCT", "3"))
MIN_VOL    = float(os.getenv("MIN_VOLUME_USDT", "500000"))
MAX_COINS  = int(os.getenv("MAX_COINS_TO_SCAN", "30"))
CORE = ["DOGE","SHIB","PEPE","BONK","WIF","FLOKI","NEIRO","WLD","SOL","BNB"]

STABLES = {"USDT","USDC","BUSD","FDUSD","DAI","TUSD"}

def fetch_binance():
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10)
        out = []
        for t in r.json():
            sym = t.get("symbol","")
            if not sym.endswith("USDT"): continue
            coin = sym[:-4]
            if coin in STABLES: continue
            chg = float(t.get("priceChangePercent", 0))
            vol = float(t.get("quoteVolume", 0))
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                out.append((coin, abs(chg), "binance"))
        log.info(f"Binance 找到 {len(out)} 個候選幣")
        return out
    except Exception as e:
        log.error(f"Binance 抓取失敗: {e}")
        return []

def fetch_okx():
    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=10)
        out = []
        for t in r.json().get("data", []):
            inst = t.get("instId","")
            if not inst.endswith("-USDT-SWAP"): continue
            coin = inst.replace("-USDT-SWAP","")
            if coin in STABLES: continue
            try:
                chg = float(t.get("sodUtc8", 0)) * 100
                vol = float(t.get("volCcy24h", 0))
            except: continue
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                out.append((coin, abs(chg), "okx"))
        log.info(f"OKX 找到 {len(out)} 個候選幣")
        return out
    except Exception as e:
        log.error(f"OKX 抓取失敗: {e}")
        return []

def fetch_bybit():
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=10)
        out = []
        for t in r.json().get("result",{}).get("list",[]):
            sym = t.get("symbol","")
            if not sym.endswith("USDT"): continue
            coin = sym[:-4]
            if coin in STABLES: continue
            try:
                chg = float(t.get("price24hPcnt", 0)) * 100
                vol = float(t.get("turnover24h", 0))
            except: continue
            if vol >= MIN_VOL and abs(chg) >= MIN_CHANGE:
                out.append((coin, abs(chg), "bybit"))
        log.info(f"Bybit 找到 {len(out)} 個候選幣")
        return out
    except Exception as e:
        log.error(f"Bybit 抓取失敗: {e}")
        return []

def get_best_candidates():
    """合併三大交易所，每個幣只保留最高漲幅的那個交易所"""
    all_coins = fetch_binance() + fetch_okx() + fetch_bybit()
    
    # 每個幣只保留漲幅最高的交易所
    best = {}
    for coin, chg, exchange in all_coins:
        if coin not in best or chg > best[coin][0]:
            best[coin] = (chg, exchange)
    
    # 按漲幅排序
    sorted_coins = sorted(best.items(), key=lambda x: x[1][0], reverse=True)
    
    # 取前MAX_COINS個
    result = [(coin, exchange) for coin, (chg, exchange) in sorted_coins[:MAX_COINS]]
    
    # 加入核心幣（如果不在列表裡）
    existing = {c[0] for c in result}
    for coin in CORE:
        if coin not in existing:
            result.append((coin, "binance"))
    
    log.info(f"最終掃描 {len(result)} 個幣種")
    return result

def main():
    log.info("═══ LANA Meme Scanner v3.0 三大交易所掃描 ═══")
    candidates = get_best_candidates()
    signals = []
    
    for coin, exchange in candidates:
        try:
            k1h  = get_all_klines(coin, exchange, "1h",  100)
            k15m = get_all_klines(coin, exchange, "15m", 100)
            k4h  = get_all_klines(coin, exchange, "4h",  50)
            
            if not k1h or not k15m:
                log.warning(f"[{exchange}] {coin} 無資料，跳過")
                continue
            
            ind = calc_indicators(k1h, k15m, k4h)
            res = analyze_coin(coin, exchange, ind)
            
            if res:
                score = res.get("score", 0)
                direction = res.get("direction", "WATCH")
                log.info(f"[{exchange}] {coin} → {direction} {score}分")
                if score >= MIN_SCORE:
                    signals.append(res)
                    
        except Exception as e:
            log.error(f"[{exchange}] {coin} 出錯: {e}")
    
    if signals:
        signals.sort(key=lambda x: x["score"], reverse=True)
        send_telegram(signals)
        log.info(f"📨 推播 {len(signals)} 個訊號")
    else:
        log.info("本輪無達標訊號")
    
    log.info("═══ 掃描完畢 ═══")

if __name__ == "__main__":
    main()

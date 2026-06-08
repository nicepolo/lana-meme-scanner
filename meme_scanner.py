"""
LANA Meme Scanner v4.0 - 三大交易所全市場掃描 + 資金費率
OKX（主力）+ Binance/Bybit（備援）+ Funding Rate 篩選
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

MIN_SCORE   = int(os.getenv("MIN_SCORE_TO_ALERT", "45"))
MIN_CHANGE  = float(os.getenv("MIN_CHANGE_PCT", "3"))
MIN_VOL     = float(os.getenv("MIN_VOLUME_USDT", "500000"))
MAX_COINS   = int(os.getenv("MAX_COINS_TO_SCAN", "30"))

# 主流幣列表（用較嚴格的資金費率邏輯）
MAJORS  = {"BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","DOT","MATIC","LINK","UNI"}
STABLES = {"USDT","USDC","BUSD","FDUSD","DAI","TUSD"}

# 資金費率門檻
FUNDING_EXTREME = 0.0005   # ±0.05%，超過這個才算異常
FUNDING_STRONG  = 0.001    # ±0.1%，非常強烈訊號


def fetch_funding_rates() -> dict:
    """抓 OKX 資金費率（Railway 可用）"""
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
    """OKX 合約市場（Railway 主力來源）"""
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
    """合併三大交易所候選幣，加入資金費率強制納入邏輯"""
    all_coins = fetch_okx() + fetch_binance() + fetch_bybit()

    # 每個幣只保留漲幅最高的交易所
    best = {}
    for coin, chg, exchange in all_coins:
        if coin not in best or chg > best[coin][0]:
            best[coin] = (chg, exchange)

    # 資金費率極端的幣強制納入（不管漲幅）
    for coin, rate in funding_rates.items():
        if abs(rate) >= FUNDING_EXTREME and coin not in STABLES:
            if coin not in best:
                best[coin] = (0, "okx")  # 資金費率強制加入

    # 排序：優先資金費率異常，其次漲幅
    def sort_key(item):
        coin, (chg, _) = item
        fr = abs(funding_rates.get(coin, 0))
        fr_score = 2 if fr >= FUNDING_STRONG else 1 if fr >= FUNDING_EXTREME else 0
        return (fr_score, chg)

    sorted_coins = sorted(best.items(), key=sort_key, reverse=True)
    result = [(coin, exchange) for coin, (chg, exchange) in sorted_coins[:MAX_COINS]]

    log.info(f"最終掃描 {len(result)} 個幣種")
    return result


def main():
    log.info("═══ LANA Meme Scanner v4.0 資金費率強化版 ═══")

    # 先抓資金費率
    funding_rates = fetch_funding_rates()

    candidates = get_best_candidates(funding_rates)
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
            ind["funding_rate"] = funding_rates.get(coin, 0)  # 注入資金費率
            res = analyze_coin(coin, exchange, ind)

            if res:
                score     = res.get("score", 0)
                direction = res.get("direction", "WATCH")
                fr        = funding_rates.get(coin, 0)

                # 主流幣：需要資金費率異常 OR RSI 極端才推
                if coin in MAJORS:
                    rsi_1h = ind.get("rsi_1h", 50)
                    fr_ok  = abs(fr) >= FUNDING_EXTREME
                    rsi_ok = rsi_1h >= 72 or rsi_1h <= 28
                    if not (fr_ok or rsi_ok):
                        log.info(f"[{exchange}] {coin} 主流幣條件不足（FR:{fr:.4f} RSI:{rsi_1h:.0f}），跳過")
                        continue

                # 加入資金費率資訊
                res["funding_rate"] = fr
                res["is_major"]     = coin in MAJORS

                log.info(f"[{exchange}] {coin} → {direction} {score}分 FR:{fr:.4f}")
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

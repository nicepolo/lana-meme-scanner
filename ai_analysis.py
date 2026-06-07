import os, json, logging, requests
log = logging.getLogger(__name__)

GEMINI_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")

def _build_prompt(symbol: str, exchange: str, indicators: dict) -> str:
    rsi_1h  = indicators.get("rsi_1h", 50)
    rsi_15m = indicators.get("rsi_15m", 50)
    macd    = indicators.get("macd", "neutral")
    vol_r   = indicators.get("vol_ratio", 1.0)
    trend   = indicators.get("trend", "neutral")
    bb_pos  = indicators.get("bb_position", 0.5)
    chg     = indicators.get("change_24h", 0)

    return f"""你是加密貨幣交易分析師。分析 {symbol}/{exchange}。
數據：RSI1h={rsi_1h:.0f} RSI15m={rsi_15m:.0f} MACD={macd} 量比={vol_r:.1f}x 趨勢={trend} 布林={bb_pos:.2f} 24h={chg:+.1f}%
用JSON回答（只輸出JSON）：
{{"direction":"LONG或SHORT或WATCH","score":0-100,"confidence":"高或中或低","summary":"一句話","reason":"技術原因","entry_zone":"價格區間","stop_loss":"止損價","target_1":"目標1","target_2":"目標2","timeframe":"持倉時間","risk_note":"風險提示"}}"""


def _call_gemini(symbol: str, prompt: str) -> dict | None:
    """呼叫 Gemini Flash（免費額度）"""
    if not GEMINI_KEY:
        return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_KEY
        }
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000}
        }
        r = requests.post(url, headers=headers, json=data, timeout=15)
        if not r.ok:
            log.warning(f"Gemini 失敗 {r.status_code}: {r.text[:100]}")
            return None
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(text)
        except Exception:
            result = {
                "direction": "WATCH",
                "score": 35,
                "confidence": "低",
                "summary": "AI分析結果解析失敗",
                "reason": "回傳格式異常",
                "entry_zone": "N/A",
                "stop_loss": "N/A",
                "target_1": "N/A",
                "target_2": "N/A",
                "timeframe": "4-8小時",
                "risk_note": "請手動確認"
            }
        result["symbol"] = symbol
        result["exchange"] = "gemini-flash"
        log.info(f"✅ Gemini 分析{symbol}: {result.get('direction')} {result.get('score')}")
        return result
    except Exception as e:
        log.error(f"Gemini 分析失敗{symbol}: {e}")
        return None


def _default_result(symbol: str, exchange: str, indicators: dict) -> dict:
    """規則式備援分析"""
    rsi  = indicators.get("rsi_1h", 50)
    vr   = indicators.get("vol_ratio", 1.0)
    trend = indicators.get("trend", "neutral")
    chg  = indicators.get("change_24h", 0)
    price = indicators.get("price", 0)

    score = 35
    if trend == "up":
        score += 15
    if vr >= 1.5:
        score += 10
    if 40 <= rsi <= 65:
        score += 10
    if chg > 5:
        score += 10
    if rsi > 75:
        score -= 15
    if vr < 0.8:
        score -= 10

    score = max(0, min(100, score))

    if score >= 60 and trend == "up":
        direction = "LONG"
    elif score <= 35 or rsi > 75:
        direction = "SHORT"
    else:
        direction = "WATCH"

    return {
        "symbol": symbol,
        "exchange": exchange,
        "direction": direction,
        "score": score,
        "confidence": "低",
        "summary": f"規則式分析：{direction}",
        "reason": f"RSI={rsi:.0f} 量比={vr:.1f}x 趨勢={trend}",
        "entry_zone": f"{price*0.99:.6g}-{price*1.01:.6g}" if price else "N/A",
        "stop_loss": f"{price*0.95:.6g}" if price else "N/A",
        "target_1": f"{price*1.05:.6g}" if price else "N/A",
        "target_2": f"{price*1.10:.6g}" if price else "N/A",
        "timeframe": "4-12小時",
        "risk_note": "土狗幣波動極大，嚴控倉位"
    }


def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict | None:
    prompt = _build_prompt(symbol, exchange, indicators)
    result = _call_gemini(symbol, prompt)
    if not result:
        result = _default_result(symbol, exchange, indicators)
    return result

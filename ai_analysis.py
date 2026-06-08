import os, json, logging, requests
log = logging.getLogger(__name__)

GEMINI_KEY    = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _build_prompt(symbol: str, exchange: str, indicators: dict) -> str:
    rsi_1h  = indicators.get("rsi_1h", 50)
    rsi_15m = indicators.get("rsi_15m", 50)
    macd    = indicators.get("macd", "neutral")
    vol_r   = indicators.get("vol_ratio", 1.0)
    trend   = indicators.get("trend", "neutral")
    bb_pos  = indicators.get("bb_position", 0.5)
    chg     = indicators.get("change_24h", 0)
    fr      = indicators.get("funding_rate", 0)
    price   = indicators.get("price", 0)

    p_entry_long  = round(price * 0.995, 6) if price else 0
    p_entry_short = round(price * 1.005, 6) if price else 0
    p_sl_long     = round(price * 0.97,  6) if price else 0
    p_sl_short    = round(price * 1.03,  6) if price else 0
    p_t1_long     = round(price * 1.04,  6) if price else 0
    p_t2_long     = round(price * 1.08,  6) if price else 0
    p_t1_short    = round(price * 0.96,  6) if price else 0
    p_t2_short    = round(price * 0.92,  6) if price else 0

    return f"""你是專業加密貨幣合約交易員，擅長短線技術分析。請根據以下指標給出交易建議。

幣種：{symbol}（{exchange}）
現價：{price}
技術指標：
- RSI 1H = {rsi_1h:.0f}（>70超買，<30超賣，45-65為健康做多區）
- RSI 15M = {rsi_15m:.0f}
- MACD = {macd}（bullish/bearish/neutral）
- 量能 = {vol_r:.1f}x（>1.5放量，<0.8縮量）
- 趨勢 = {trend}（up/down/neutral）
- 布林位置 = {bb_pos:.2f}（0=下軌，1=上軌，>1突破上軌）
- 24H漲幅 = {chg:+.1f}%
- 資金費率 = {fr:+.4f}

評分標準（score 0-100，請積極評分，不要保守）：
- 趨勢向上+RSI在45-65健康區+量能>1.5x → 基礎65-75分（做多）
- 趨勢向上+RSI在45-70+量能>1.0x → 基礎55-65分
- RSI>72或布林>0.85 → 超買風險，扣15-20分
- RSI<30+趨勢向下 → 做空機會，60-70分
- 資金費率極端(>0.001) → 反向機會，加10分
- 中性盤整缺乏方向 → 40-50分

方向判斷（direction）：
- score>=60且趨勢up且RSI<72 → LONG
- RSI>75或(資金費率>0.001且趨勢!=up) → SHORT
- 其他 → WATCH

請提供入場建議（entry_zone、stop_loss、target_1、target_2是否為0或None，請用現價計算實際數字）：
- 做多建議：入場 {p_entry_long}，止損 {p_sl_long}，目標1 {p_t1_long}，目標2 {p_t2_long}
- 做空建議：入場 {p_entry_short}，止損 {p_sl_short}，目標1 {p_t1_short}，目標2 {p_t2_short}

只回傳JSON，不要其他文字：
{{"direction":"LONG或SHORT或WATCH","score":數字,"confidence":"高或中或低","summary":"一句話分析重點","reason":"RSI={rsi_1h:.0f} 量能={vol_r:.1f}x 趨勢={trend} FR={fr:+.4f}","entry_zone":"{p_entry_long}附近（積極做多用現價計算）","stop_loss":數字,"target_1":數字,"target_2":數字,"timeframe":"預期持倉時間","risk_note":"風險提示"}}"""


def _call_gemini(symbol: str, prompt: str) -> dict | None:
    if not GEMINI_KEY:
        return None
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY}
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}
        }
        r = requests.post(url, headers=headers, json=data, timeout=20)
        if not r.ok:
            log.warning(f"Gemini 失敗 {r.status_code}: {r.text[:100]}")
            return None
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        result["symbol"]   = symbol
        result["exchange"] = "gemini-flash"
        log.info(f"✅ Gemini {symbol}: {result.get('direction')} {result.get('score')}分")
        return result
    except Exception as e:
        log.error(f"Gemini 失敗 {symbol}: {e}")
        return None


def _call_claude(symbol: str, prompt: str) -> dict | None:
    if not ANTHROPIC_KEY:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=20
        )
        if not r.ok:
            return None
        text = r.json()["content"][0]["text"]
        text = text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        result["symbol"]   = symbol
        result["exchange"] = "claude-haiku"
        log.info(f"✅ Claude {symbol}: {result.get('direction')} {result.get('score')}分")
        return result
    except Exception as e:
        log.error(f"Claude 失敗 {symbol}: {e}")
        return None


def _default_result(symbol: str, exchange: str, indicators: dict) -> dict:
    """AI全部失敗時的規則式備用（積極版）"""
    rsi   = indicators.get("rsi_1h", 50)
    vr    = indicators.get("vol_ratio", 1.0)
    trend = indicators.get("trend", "neutral")
    chg   = indicators.get("change_24h", 0)
    price = indicators.get("price", 0)
    fr    = indicators.get("funding_rate", 0)

    score = 45  # 備用基礎分提高到45

    if trend == "up":       score += 15
    if trend == "down":     score -= 10
    if vr >= 2.0:           score += 15
    elif vr >= 1.5:         score += 10
    elif vr >= 1.2:         score += 5
    if 45 <= rsi <= 65:     score += 12
    elif 65 < rsi <= 70:    score += 5
    if chg > 5:             score += 8
    if chg > 10:            score += 5
    if abs(fr) >= 0.001:    score += 10
    elif abs(fr) >= 0.0005: score += 5

    # 減分
    if rsi > 75:            score -= 20
    if rsi < 25:            score += 10
    if vr < 0.8:            score -= 10

    score = max(0, min(100, score))

    if score >= 60 and trend == "up" and rsi < 72:
        direction = "LONG"
    elif rsi > 75 or (fr > 0.001 and trend != "up"):
        direction = "SHORT"
        score = max(score, 55)
    elif score < 40:
        direction = "WATCH"
    else:
        direction = "LONG" if trend == "up" else "WATCH"

    conf = "高" if score >= 65 else "中" if score >= 45 else "低"

    return {
        "symbol":     symbol,
        "exchange":   exchange,
        "direction":  direction,
        "score":      score,
        "confidence": conf,
        "summary":    f"規則式分析：{direction}",
        "reason":     f"RSI={rsi:.0f} 量能={vr:.1f}x 趨勢={trend} FR={fr:+.4f}",
        "entry_zone": f"{price*0.99:.6g}-{price*1.01:.6g}" if price else "N/A",
        "stop_loss":  f"{price*0.97:.6g}" if price else "N/A",
        "target_1":   f"{price*1.04:.6g}" if price else "N/A",
        "target_2":   f"{price*1.08:.6g}" if price else "N/A",
        "timeframe":  "4-12小時",
        "risk_note":  "規則式備用，嚴控倉位"
    }


def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict | None:
    prompt = _build_prompt(symbol, exchange, indicators)
    result = _call_gemini(symbol, prompt)
    if not result:
        result = _call_claude(symbol, prompt)
    if not result:
        result = _default_result(symbol, exchange, indicators)
    return result

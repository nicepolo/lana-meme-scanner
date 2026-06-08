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

    # 計算參考價位給 AI
    p_entry_long  = round(price * 0.995, 6) if price else 0
    p_entry_short = round(price * 1.005, 6) if price else 0
    p_sl_long     = round(price * 0.97,  6) if price else 0
    p_sl_short    = round(price * 1.03,  6) if price else 0
    p_t1_long     = round(price * 1.04,  6) if price else 0
    p_t2_long     = round(price * 1.08,  6) if price else 0
    p_t1_short    = round(price * 0.96,  6) if price else 0
    p_t2_short    = round(price * 0.92,  6) if price else 0

    return f"""你是專業加密貨幣短線交易員，根據技術指標給出明確交易建議。

幣種：{symbol}（{exchange}）
現價：{price}
技術數據：
- RSI 1H = {rsi_1h:.0f}（>70超買，<30超賣）
- RSI 15M = {rsi_15m:.0f}
- MACD = {macd}（bullish/bearish/neutral）
- 量比 = {vol_r:.1f}x（>2倍放量，<0.8縮量）
- 趨勢 = {trend}（up/down/neutral）
- 布林位置 = {bb_pos:.2f}（0=下軌，1=上軌，>1突破）
- 24H漲幅 = {chg:+.1f}%
- 資金費率 = {fr:+.4f}

參考價位（請根據技術分析調整為真實數字）：
- 做多參考：進場 {p_entry_long}，止損 {p_sl_long}，目標1 {p_t1_long}，目標2 {p_t2_long}
- 做空參考：進場 {p_entry_short}，止損 {p_sl_short}，目標1 {p_t1_short}，目標2 {p_t2_short}

評分規則（score 0-100）：
- 60-100分 = 有明確交易機會，direction應為LONG或SHORT
- 40-59分 = 有潛在機會但需確認
- 0-39分 = 無明確機會，direction=WATCH

重要：entry_zone、stop_loss、target_1、target_2 必須是真實數字價格，不能用文字描述。

只輸出JSON，不要其他文字：
{{"direction":"LONG或SHORT或WATCH","score":數字,"confidence":"高或中或低","summary":"一句話說明機會","reason":"具體技術原因","entry_zone":"{p_entry_long}附近（根據分析調整）","stop_loss":數字,"target_1":數字,"target_2":數字,"timeframe":"建議持倉時間","risk_note":"主要風險"}}"""


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
    """規則式備援分析（AI 全部失敗時使用）"""
    rsi   = indicators.get("rsi_1h", 50)
    vr    = indicators.get("vol_ratio", 1.0)
    trend = indicators.get("trend", "neutral")
    chg   = indicators.get("change_24h", 0)
    price = indicators.get("price", 0)
    fr    = indicators.get("funding_rate", 0)

    score = 40  # 基礎分提高到 40

    # 加分條件
    if trend == "up":       score += 15
    if trend == "down":     score -= 10
    if vr >= 2.0:           score += 15
    elif vr >= 1.5:         score += 8
    if 45 <= rsi <= 65:     score += 10
    if chg > 5:             score += 8
    if chg > 10:            score += 5
    if abs(fr) >= 0.001:    score += 10  # 資金費率極端
    if abs(fr) >= 0.0005:   score += 5

    # 減分條件
    if rsi > 78:            score -= 15
    if rsi < 25:            score += 10  # 超賣反而加分
    if vr < 0.8:            score -= 10

    score = max(0, min(100, score))

    # 方向判斷
    if score >= 55 and trend == "up" and rsi < 72:
        direction = "LONG"
    elif rsi > 75 or (fr > 0.001 and trend != "up"):
        direction = "SHORT"
        score = max(score, 55)
    elif score < 40:
        direction = "WATCH"
    else:
        direction = "LONG" if trend == "up" else "WATCH"

    return {
        "symbol":     symbol,
        "exchange":   exchange,
        "direction":  direction,
        "score":      score,
        "confidence": "低",
        "summary":    f"規則式分析：{direction}",
        "reason":     f"RSI={rsi:.0f} 量比={vr:.1f}x 趨勢={trend} FR={fr:+.4f}",
        "entry_zone": f"{price*0.99:.6g}-{price*1.01:.6g}" if price else "N/A",
        "stop_loss":  f"{price*0.95:.6g}" if price else "N/A",
        "target_1":   f"{price*1.05:.6g}" if price else "N/A",
        "target_2":   f"{price*1.10:.6g}" if price else "N/A",
        "timeframe":  "4-12小時",
        "risk_note":  "土狗幣波動極大，嚴控倉位"
    }


def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict | None:
    prompt = _build_prompt(symbol, exchange, indicators)
    result = _call_gemini(symbol, prompt)
    if not result:
        result = _call_claude(symbol, prompt)
    if not result:
        result = _default_result(symbol, exchange, indicators)
    return result

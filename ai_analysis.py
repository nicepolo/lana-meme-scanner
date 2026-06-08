"""
ai_analysis.py - 統一評分版
- LANA Score 計算邏輯與網頁完全一致
- AI 只負責寫分析摘要文字，不決定分數
- AI 失敗時用規則式摘要，分數不受影響
"""
import os, json, logging, requests
log = logging.getLogger(__name__)

GEMINI_KEY    = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _calc_lana_score(indicators: dict) -> tuple[int, str]:
    """
    與網頁 calc_lana_score 完全一致的評分邏輯（使用 MA 排列判斷趨勢）
    回傳 (score, bb_zone)
    """
    rsi   = indicators.get("rsi_1h", 50)
    vr    = indicators.get("vol_ratio", indicators.get("vol_ratio_1h", 1.0))
    fr    = indicators.get("funding_rate", 0)

    # BB 位置：優先用 bb_1h dict，備用 bb_position float
    bb_data = indicators.get("bb_1h", {})
    if isinstance(bb_data, dict):
        bb = bb_data.get("pct_b", 0.5)
    else:
        bb = indicators.get("bb_position", 0.5)

    # ── 趨勢 25分：用 MA7/MA25/MA99 排列（對齊 lana-monitor MA7/MA30/MA120）──
    ma7  = indicators.get("ma7_1h")
    ma25 = indicators.get("ma25_1h")
    ma99 = indicators.get("ma99_1h")
    price = indicators.get("price", 0)
    if ma7 and ma25 and ma99 and ma7 > ma25 > ma99:
        s_trend = 25   # 多頭排列
    elif ma7 and ma25 and ma7 > ma25:
        s_trend = 15   # 短線偏多
    elif ma7 and ma25 and ma7 < ma25:
        s_trend = 0    # 空頭排列
    else:
        s_trend = 5    # 資料不足

    # ── RSI 20分 ──
    if rsi is None:          s_rsi = 10
    elif 50 <= rsi < 70:     s_rsi = 20
    elif 40 <= rsi < 50:     s_rsi = 15
    elif 30 <= rsi < 40:     s_rsi = 10
    elif 70 <= rsi < 80:     s_rsi = 8
    else:                    s_rsi = 0   # <30 或 >=80

    # ── 量能 20分 ──
    if vr is None:   s_vol = 10
    elif vr >= 2.0:  s_vol = 20
    elif vr >= 1.5:  s_vol = 16
    elif vr >= 1.0:  s_vol = 12
    elif vr >= 0.8:  s_vol = 6
    else:            s_vol = 0

    # ── BB位置 15分 ──
    if bb < 0.5:     s_bb = 15   # 下半部（支撐）
    elif bb <= 1.0:  s_bb = 8    # 上半部
    else:            s_bb = 0    # 突破上軌（超買）

    # ── 資金費率調整（替代風險分）20分 ──
    if abs(fr) < 0.0001:     s_risk = 20   # 中性
    elif abs(fr) < 0.0005:   s_risk = 15
    elif fr < -0.0005:       s_risk = 18   # 負費率，做多有利
    elif fr > 0.001:         s_risk = 2    # 極端正費率，多頭擁擠
    else:                    s_risk = 8

    score = s_trend + s_rsi + s_vol + s_bb + s_risk
    score = max(0, min(100, score))

    # BB區間描述
    if bb > 1.0:    bb_zone = "above_upper"
    elif bb > 0.5:  bb_zone = "upper_half"
    elif bb >= 0:   bb_zone = "lower_half"
    else:           bb_zone = "below_lower"

    return score, bb_zone


def _get_direction(score: int, indicators: dict) -> str:
    rsi  = indicators.get("rsi_1h", 50)
    fr   = indicators.get("funding_rate", 0)
    ma7  = indicators.get("ma7_1h")
    ma25 = indicators.get("ma25_1h")
    ma99 = indicators.get("ma99_1h")

    # 判斷趨勢方向
    if ma7 and ma25 and ma7 > ma25:
        trend_up = True
    else:
        trend_up = False

    if score >= 70 and trend_up and rsi < 72:
        return "LONG"
    elif rsi > 75 or (fr > 0.001 and not trend_up):
        return "SHORT"
    elif score < 50:
        return "WATCH"
    else:
        return "WATCH"  # 分數不足或趨勢不明，一律觀望


def _build_summary_prompt(symbol: str, exchange: str, indicators: dict, score: int, direction: str) -> str:
    rsi   = indicators.get("rsi_1h", 50)
    vr    = indicators.get("vol_ratio", 1.0)
    trend = indicators.get("trend", "neutral")
    bb    = indicators.get("bb_position", 0.5)
    chg   = indicators.get("change_24h", 0)
    fr    = indicators.get("funding_rate", 0)
    price = indicators.get("price", 0)

    return f"""你是加密貨幣交易員，請根據以下數據寫一段簡短分析（繁體中文）。

幣種：{symbol}（{exchange}）現價：{price}
LANA評分：{score}/100  方向建議：{direction}
RSI 1H={rsi:.0f} | 量能={vr:.1f}x | 趨勢={trend} | BB位置={bb:.2f} | 24H={chg:+.1f}% | FR={fr:+.4f}

請只回傳JSON，不要其他文字：
{{"summary":"一句話點出最關鍵的訊號（15字內）","reason":"列出2-3個具體數據支撐","risk_note":"最主要的一個風險","timeframe":"建議持倉時間如4-8小時","entry_zone":"{round(price*0.995,4)}-{round(price*1.005,4)}","stop_loss":{round(price*0.97,4)},"target_1":{round(price*1.04,4)},"target_2":{round(price*1.08,4)}}}"""


def _call_gemini(symbol: str, prompt: str) -> dict | None:
    if not GEMINI_KEY:
        return None
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        r = requests.post(url,
            headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}},
            timeout=15)
        if not r.ok:
            return None
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception as e:
        log.error(f"Gemini 失敗 {symbol}: {e}")
        return None


def _call_claude(symbol: str, prompt: str) -> dict | None:
    if not ANTHROPIC_KEY:
        return None
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 300,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=15)
        if not r.ok:
            return None
        text = r.json()["content"][0]["text"]
        text = text.strip().replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception as e:
        log.error(f"Claude 失敗 {symbol}: {e}")
        return None


def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict | None:
    # 1. 用統一規則算分（跟網頁一致）
    score, bb_zone = _calc_lana_score(indicators)
    direction      = _get_direction(score, indicators)

    price = indicators.get("price", 0)
    rsi   = indicators.get("rsi_1h", 50)
    vr    = indicators.get("vol_ratio", 1.0)
    trend = indicators.get("trend", "neutral")
    fr    = indicators.get("funding_rate", 0)

    # 2. 嘗試讓 AI 寫摘要（不決定分數）
    ai_data = None
    if score >= 45:   # 只有可能達標的才花 API
        prompt  = _build_summary_prompt(symbol, exchange, indicators, score, direction)
        ai_data = _call_gemini(symbol, prompt) or _call_claude(symbol, prompt)

    # 3. 組裝最終結果（分數永遠來自規則式）
    conf = "高" if score >= 65 else "中" if score >= 45 else "低"

    result = {
        "symbol":     symbol,
        "exchange":   exchange,
        "direction":  direction,
        "score":      score,
        "confidence": conf,
        "summary":    ai_data.get("summary", f"{direction} 訊號") if ai_data else f"規則式：{direction}",
        "reason":     ai_data.get("reason",  f"RSI={rsi:.0f} 量能={vr:.1f}x 趨勢={trend}") if ai_data else f"RSI={rsi:.0f} 量能={vr:.1f}x 趨勢={trend} FR={fr:+.4f}",
        "risk_note":  ai_data.get("risk_note", "嚴控倉位，設好止損") if ai_data else "嚴控倉位，設好止損",
        "timeframe":  ai_data.get("timeframe", "4-8小時") if ai_data else "4-8小時",
        "entry_zone": ai_data.get("entry_zone", f"{round(price*0.995,6)}-{round(price*1.005,6)}") if ai_data else f"{round(price*0.995,6)}-{round(price*1.005,6)}",
        "stop_loss":  ai_data.get("stop_loss",  round(price*0.97, 6)) if ai_data else round(price*0.97, 6),
        "target_1":   ai_data.get("target_1",   round(price*1.04, 6)) if ai_data else round(price*1.04, 6),
        "target_2":   ai_data.get("target_2",   round(price*1.08, 6)) if ai_data else round(price*1.08, 6),
    }

    log.info(f"{'✅' if score>=65 else '📊'} {symbol}: {direction} {score}分 ({conf}信心) [{'AI' if ai_data else '規則式'}摘要]")
    return result

"""
ai_analysis.py — 呼叫 Claude API 分析盤面，給出做多/做空/觀望建議
"""

import os
import json
import logging
import requests

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"


def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict | None:
    """
    送技術指標給 Claude，取回結構化分析結果
    回傳 dict 或 None（分析失敗時）
    """
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY 未設定，無法進行 AI 分析")
        return _fallback_analysis(symbol, exchange, indicators)

    prompt = _build_prompt(symbol, exchange, indicators)

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": MODEL,
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["text"]
        return _parse_response(symbol, exchange, indicators, content)

    except Exception as e:
        log.error(f"Claude API 呼叫失敗 [{exchange}] {symbol}: {e}")
        return _fallback_analysis(symbol, exchange, indicators)


def _build_prompt(symbol: str, exchange: str, ind: dict) -> str:
    price = ind.get("price", 0)
    rsi_1h = ind.get("rsi_1h", 50)
    rsi_15m = ind.get("rsi_15m", 50)
    rsi_4h = ind.get("rsi_4h", "N/A")
    macd_1h = ind.get("macd_1h", {})
    macd_15m = ind.get("macd_15m", {})
    bb_1h = ind.get("bb_1h", {})
    bb_15m = ind.get("bb_15m", {})
    ma7_1h = ind.get("ma7_1h", 0)
    ma25_1h = ind.get("ma25_1h", 0)
    ma99_1h = ind.get("ma99_1h", 0)
    vol_ratio_1h = ind.get("vol_ratio_1h", 1)
    change_24h = ind.get("price_change_24h", 0)
    trend_4h = ind.get("trend_4h", "unknown")

    return f"""你是一位專業加密貨幣技術分析師，專門分析土狗幣（Meme Coin）的短線交易機會。
請根據以下技術指標，給出嚴謹的多空建議。

幣種：{symbol}/USDT
交易所：{exchange}
現價：{price}
24h 漲跌：{change_24h}%

【技術指標】
4H 趨勢：{trend_4h}
4H RSI：{rsi_4h}

1H RSI：{rsi_1h}
1H MACD hist：{macd_1h.get('hist', 0):.8f}  交叉狀態：{macd_1h.get('cross', 'none')}
1H 布林位置：{bb_1h.get('position', 'unknown')}  %B：{bb_1h.get('pct_b', 0.5)}
1H MA7：{ma7_1h}  MA25：{ma25_1h}  MA99：{ma99_1h}

15M RSI：{rsi_15m}
15M MACD hist：{macd_15m.get('hist', 0):.8f}  交叉狀態：{macd_15m.get('cross', 'none')}
15M 布林位置：{bb_15m.get('position', 'unknown')}  %B：{bb_15m.get('pct_b', 0.5)}

量能比（現量/均量）：{vol_ratio_1h}x

請輸出以下 JSON 格式（只輸出 JSON，不要加其他文字）：
{{
  "direction": "LONG" | "SHORT" | "WATCH",
  "score": 整數 0-100（訊號強度，>=60 才值得交易）,
  "confidence": "高" | "中" | "低",
  "summary": "一句話總結（繁體中文，20字以內）",
  "reason": "技術分析理由（繁體中文，60字以內）",
  "entry_zone": "建議入場價格範圍（例：0.00001200-0.00001230）",
  "stop_loss": "建議止損價格",
  "target_1": "第一目標價",
  "target_2": "第二目標價（較遠）",
  "risk_note": "風險提示（繁體中文，20字以內）",
  "timeframe": "預計持倉時間（例：4-12小時）"
}}"""


def _parse_response(symbol: str, exchange: str, indicators: dict, content: str) -> dict | None:
    """解析 Claude 回應的 JSON"""
    try:
        # 清除可能的 markdown 包裝
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        data = json.loads(content)
        data["symbol"]   = symbol
        data["exchange"] = exchange
        data["price"]    = indicators.get("price", 0)
        data["change_24h"] = indicators.get("price_change_24h", 0)
        data["vol_ratio"]  = indicators.get("vol_ratio_1h", 1)
        data["rsi_1h"]     = indicators.get("rsi_1h", 50)

        # 強制確保 score 是整數
        data["score"] = int(data.get("score", 0))
        return data

    except Exception as e:
        log.error(f"解析 Claude 回應失敗: {e}\n原始內容: {content[:200]}")
        return None


def _fallback_analysis(symbol: str, exchange: str, indicators: dict) -> dict | None:
    """
    沒有 API Key 時的純規則分析（備用）
    """
    rsi_1h = indicators.get("rsi_1h", 50)
    rsi_15m = indicators.get("rsi_15m", 50)
    macd_1h = indicators.get("macd_1h", {})
    bb_1h = indicators.get("bb_1h", {})
    vol_ratio = indicators.get("vol_ratio_1h", 1)
    price = indicators.get("price", 0)
    change_24h = indicators.get("price_change_24h", 0)

    score = 50
    direction = "WATCH"
    reasons = []

    # RSI 判斷
    if rsi_1h < 35 and rsi_15m < 40:
        score += 15
        direction = "LONG"
        reasons.append("RSI 超賣")
    elif rsi_1h > 70 and rsi_15m > 65:
        score += 15
        direction = "SHORT"
        reasons.append("RSI 超買")

    # MACD 判斷
    if macd_1h.get("cross") == "golden":
        score += 10
        if direction != "SHORT":
            direction = "LONG"
        reasons.append("MACD 金叉")
    elif macd_1h.get("cross") == "death":
        score += 10
        if direction != "LONG":
            direction = "SHORT"
        reasons.append("MACD 死叉")

    # 布林判斷
    bb_pos = bb_1h.get("position", "middle")
    if bb_pos == "below_lower":
        score += 8
        reasons.append("跌破布林下軌")
    elif bb_pos == "above_upper":
        score += 8
        direction = "SHORT" if direction == "WATCH" else direction
        reasons.append("突破布林上軌")

    # 量能
    if vol_ratio > 2.0:
        score += 10
        reasons.append(f"放量 {vol_ratio}x")

    # 24h 大漲後回落機會
    if change_24h > 20 and rsi_1h > 65:
        score = max(score, 60)
        direction = "SHORT"
        reasons.append(f"24h 漲 {change_24h}% 超買")

    if not reasons:
        return None  # 無明顯訊號

    bb_mid = bb_1h.get("middle", price)
    bb_lower = bb_1h.get("lower", price * 0.97)
    bb_upper = bb_1h.get("upper", price * 1.03)

    if direction == "LONG":
        entry = f"{price * 0.995:.8g} - {price:.8g}"
        stop_loss = str(round(bb_lower * 0.995, 8))
        t1 = str(round(bb_mid, 8))
        t2 = str(round(bb_upper * 0.99, 8))
    elif direction == "SHORT":
        entry = f"{price:.8g} - {price * 1.005:.8g}"
        stop_loss = str(round(bb_upper * 1.005, 8))
        t1 = str(round(bb_mid, 8))
        t2 = str(round(bb_lower * 1.01, 8))
    else:
        return None

    return {
        "symbol":    symbol,
        "exchange":  exchange,
        "direction": direction,
        "score":     min(score, 85),
        "confidence": "中",
        "summary":   "，".join(reasons[:2]),
        "reason":    " | ".join(reasons),
        "entry_zone": entry,
        "stop_loss":  stop_loss,
        "target_1":   t1,
        "target_2":   t2,
        "risk_note":  "土狗幣波動極大，嚴控倉位",
        "timeframe":  "4-12小時",
        "price":      price,
        "change_24h": change_24h,
        "vol_ratio":  vol_ratio,
        "rsi_1h":     rsi_1h
    }

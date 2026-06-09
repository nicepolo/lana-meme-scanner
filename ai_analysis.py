"""
ai_analysis.py - 純規則式版本（零 AI API 費用）
- 分數完全由技術指標決定（MA排列、RSI、BB、量能、資金費率）
- 說明文字由規則自動生成，穩定不受 AI 服務影響
- 深度分析頁的 AI 功能另外保留，不受影響
"""
import os, logging
log = logging.getLogger(__name__)


def _calc_lana_score(indicators: dict) -> tuple:
    """技術指標評分，與 lana-monitor 標準一致，回傳 (score, bb_zone)"""
    rsi  = indicators.get("rsi_1h", 50)
    vr   = indicators.get("vol_ratio", indicators.get("vol_ratio_1h", 1.0))
    fr   = indicators.get("funding_rate", 0)

    # BB 位置
    bb_data = indicators.get("bb_1h", {})
    if isinstance(bb_data, dict):
        bb      = bb_data.get("pct_b", 0.5)
        bb_zone = bb_data.get("position", "middle")
    else:
        bb      = indicators.get("bb_position", 0.5)
        bb_zone = "lower_half" if bb < 0.5 else "upper_half"

    # ── 趨勢 25分：MA排列 ──
    ma7  = indicators.get("ma7_1h")
    ma25 = indicators.get("ma25_1h")
    ma99 = indicators.get("ma99_1h")
    if ma7 and ma25 and ma99 and ma7 > ma25 > ma99:
        s_trend = 25
    elif ma7 and ma25 and ma7 > ma25:
        s_trend = 15
    elif ma7 and ma25 and ma7 < ma25:
        s_trend = 0
    else:
        s_trend = 5

    # ── RSI 20分 ──
    if rsi is None:          s_rsi = 10
    elif 50 <= rsi < 70:     s_rsi = 20
    elif 40 <= rsi < 50:     s_rsi = 15
    elif 30 <= rsi < 40:     s_rsi = 10
    elif 70 <= rsi < 80:     s_rsi = 8
    else:                    s_rsi = 0

    # ── 量能 20分 ──
    if vr is None:   s_vol = 10
    elif vr >= 2.0:  s_vol = 20
    elif vr >= 1.5:  s_vol = 16
    elif vr >= 1.0:  s_vol = 12
    elif vr >= 0.8:  s_vol = 6
    else:            s_vol = 0

    # ── BB位置 15分 ──
    if bb < 0.3:     s_bb = 15
    elif bb < 0.5:   s_bb = 12
    elif bb <= 0.7:  s_bb = 8
    elif bb <= 1.0:  s_bb = 4
    else:            s_bb = 0

    # ── 資金費率 20分 ──
    if abs(fr) < 0.0001:     s_risk = 20
    elif abs(fr) < 0.0005:   s_risk = 15
    elif fr < -0.0005:       s_risk = 18
    elif fr > 0.001:         s_risk = 2
    else:                    s_risk = 8

    score = max(0, min(100, s_trend + s_rsi + s_vol + s_bb + s_risk))
    return score, bb_zone


def _get_direction(score: int, indicators: dict) -> str:
    rsi  = indicators.get("rsi_1h", 50)
    fr   = indicators.get("funding_rate", 0)
    ma7  = indicators.get("ma7_1h")
    ma25 = indicators.get("ma25_1h")
    ma99 = indicators.get("ma99_1h")
    # 對齊 lana-monitor：三條均線全排才算真多頭
    trend_full = bool(ma7 and ma25 and ma99 and ma7 > ma25 > ma99)
    trend_mild = bool(ma7 and ma25 and ma7 > ma25)

    if score >= 70 and trend_full and rsi < 72:
        return "LONG"
    elif rsi > 75 or (fr > 0.001 and not trend_mild):
        return "SHORT"
    else:
        return "WATCH"


def _build_summary(symbol: str, score: int, direction: str, indicators: dict, bb_zone: str) -> dict:
    """純規則生成摘要文字，零 API 費用"""
    rsi   = indicators.get("rsi_1h", 50)
    vr    = indicators.get("vol_ratio", indicators.get("vol_ratio_1h", 1.0))
    fr    = indicators.get("funding_rate", 0)
    chg   = indicators.get("change_24h", indicators.get("price_change_24h", 0))
    price = indicators.get("price", 0)
    ma7   = indicators.get("ma7_1h")
    ma25  = indicators.get("ma25_1h")
    ma99  = indicators.get("ma99_1h")

    # 趨勢描述
    if ma7 and ma25 and ma99 and ma7 > ma25 > ma99:
        trend_txt = "MA三線多頭排列"      # 對齊 lana-monitor 真多頭標準
    elif ma7 and ma25 and ma7 > ma25:
        trend_txt = "短線偏多MA99未跟上"  # 假多頭，需謹慎
    else:
        trend_txt = "MA空頭或整理"

    # RSI 描述
    if rsi >= 70:   rsi_txt = f"RSI={rsi:.0f}超買注意回調"
    elif rsi >= 55: rsi_txt = f"RSI={rsi:.0f}中位偏強"
    elif rsi >= 45: rsi_txt = f"RSI={rsi:.0f}中性整理"
    elif rsi >= 30: rsi_txt = f"RSI={rsi:.0f}偏弱有反彈機會"
    else:           rsi_txt = f"RSI={rsi:.0f}超賣反彈訊號"

    # 量能描述
    if vr >= 2.0:   vol_txt = f"量能{vr:.1f}x放量強勁"
    elif vr >= 1.5: vol_txt = f"量能{vr:.1f}x溫和放量"
    elif vr >= 1.0: vol_txt = f"量能{vr:.1f}x平穩"
    else:           vol_txt = f"量能{vr:.1f}x偏弱"

    # BB 描述
    bb_map = {
        "below_lower": "價格跌破布林下軌",
        "lower_half":  "布林下軌支撐區",
        "upper_half":  "布林上半部",
        "above_upper": "突破布林上軌超買",
    }
    bb_txt = bb_map.get(bb_zone, "布林中軌附近")

    # 資金費率
    if fr > 0.001:    fr_txt = "資金費率極高多頭擁擠"
    elif fr < -0.001: fr_txt = "負費率空頭擁擠反指標"
    elif abs(fr) < 0.0001: fr_txt = ""
    else:             fr_txt = f"FR={fr*100:+.3f}%"

    # 組裝 summary（一句話）
    if direction == "LONG":
        if score >= 85:
            summary = f"{trend_txt}，{rsi_txt}，強力做多機會"
        elif score >= 70:
            summary = f"{trend_txt}，{rsi_txt}，{vol_txt}"
        else:
            summary = f"看多但需確認，{vol_txt}"
    elif direction == "SHORT":
        summary = f"做空訊號，{rsi_txt}，{bb_txt}"
    else:
        summary = f"觀望整理，{trend_txt}，{vol_txt}"

    # reason（2-3個數據點）
    reasons = [rsi_txt, bb_txt, vol_txt]
    if fr_txt:
        reasons.append(fr_txt)
    if chg != 0:
        reasons.append(f"24H{chg:+.1f}%")
    reason = "；".join(reasons[:3])

    # risk_note
    if rsi >= 70:
        risk_note = f"RSI已進入超買區（>{70}臨界值），短期回調風險較大"
    elif vr < 1.0:
        risk_note = f"量能僅{vr:.1f}x偏弱，突破乏力風險，需等待成交量配合"
    elif fr > 0.0005:
        risk_note = f"資金費率偏高，多頭持倉成本上升，注意被擠壓"
    elif bb_zone == "above_upper":
        risk_note = "價格突破布林上軌，短線超買，謹防假突破"
    else:
        risk_note = "嚴控倉位，設好止損，單筆不超 3-5%"

    # 入場/止損/目標
    if price > 0:
        if direction == "SHORT":
            entry  = f"{round(price*1.002,4)}-{round(price*1.008,4)}"
            sl     = round(price * 1.03, 4)
            t1     = round(price * 0.96, 4)
            t2     = round(price * 0.92, 4)
        else:
            entry  = f"{round(price*0.993,4)}-{round(price*1.005,4)}"
            sl     = round(price * 0.97, 4)
            t1     = round(price * 1.04, 4)
            t2     = round(price * 1.08, 4)
    else:
        entry, sl, t1, t2 = "N/A", "N/A", "N/A", "N/A"

    return {
        "summary":    summary,
        "reason":     reason,
        "risk_note":  risk_note,
        "timeframe":  "4-8小時",
        "entry_zone": entry,
        "stop_loss":  sl,
        "target_1":   t1,
        "target_2":   t2,
    }


def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict | None:
    score, bb_zone = _calc_lana_score(indicators)
    direction      = _get_direction(score, indicators)
    conf           = "高" if score >= 70 else "中" if score >= 50 else "低"

    txt = _build_summary(symbol, score, direction, indicators, bb_zone)

    result = {
        "symbol":     symbol,
        "exchange":   exchange,
        "direction":  direction,
        "score":      score,
        "confidence": conf,
        **txt,
    }

    log.info(f"{'✅' if score>=70 else '📊'} {symbol}: {direction} {score}分 ({conf}信心) [規則式]")
    return result

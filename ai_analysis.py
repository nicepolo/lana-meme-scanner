"""
ai_analysis.py — AI 多空分析
主力：Gemini Flash（免費額度）
備援：Claude Haiku（高分訊號才用）
快取：30分鐘內不重複分析，省費用
"""

import os, logging, requests, json, time
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

GEMINI_KEY     = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

# 快取：{symbol: {result, expire_ts}}
_cache = {}
CACHE_MIN = 30  # 快取30分鐘

def analyze_coin(symbol: str, exchange: str, indicators: dict) -> dict:
    """主入口：Gemini Flash 分析，失敗才用 Claude"""

    # 1. 快取檢查
    now = time.time()
    if symbol in _cache and _cache[symbol]["expire"] > now:
        log.info(f"快取命中: {symbol}")
        return _cache[symbol]["result"]

    # 2. 準備精簡 prompt（減少 token 消耗）
    prompt = _build_prompt(symbol, exchange, indicators)

    # 3. 先用 Gemini（免費）
    result = None
    if GEMINI_KEY:
        result = _call_gemini(symbol, prompt)

    # 4. Gemini 失敗才用 Claude（備援）
    if not result and ANTHROPIC_KEY:
        result = _call_claude(symbol, prompt)

    # 5. 都失敗則回傳預設
    if not result:
        result = _default_result(symbol, indicators)

    # 6. 存快取
    _cache[symbol] = {"result": result, "expire": now + CACHE_MIN * 60}
    # 清理過期快取
    expired = [k for k, v in _cache.items() if v["expire"] < now]
    for k in expired:
        del _cache[k]

    return result


def _build_prompt(symbol: str, exchange: str, indicators: dict) -> str:
    """精簡 prompt，減少 token"""
    rsi_1h  = indicators.get("rsi_1h", 50)
    rsi_15m = indicators.get("rsi_15m", 50)
    macd    = indicators.get("macd_signal", "neutral")
    vol_r   = indicators.get("vol_ratio", 1.0)
    trend   = indicators.get("trend", "sideways")
    price   = indicators.get("price", 0)
    chg     = indicators.get("change_24h", 0)
    bb_pos  = indicators.get("bb_position", 0.5)

    return f"""你是加密貨幣交易分析師。分析 {symbol}/{exchange}。

數據：RSI1h={rsi_1h:.0f} RSI15m={rsi_15m:.0f} MACD={macd} 量比={vol_r:.1f}x 趨勢={trend} 布林={bb_pos:.2f} 24h={chg:+.1f}%

用JSON回答（只輸出JSON）：
{{"direction":"LONG或SHORT或WATCH","score":0-100,"confidence":"高或中或低","summary":"一句話","reason":"技術原因","entry_zone":"進場區間","stop_loss":"止損","target_1":"目標1","target_2":"目標2","timeframe":"持倉時間","risk_note":"風險提示"}}"""


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
            # JSON 截斷，給預設值
            result = {
                "direction": "WATCH", "score": 35,
                "confidence": "低", "summary": "AI分析結果解析失敗",
                "reason": "回傳格式異常", "entry_zone": "N/A",
                "stop_loss": "N/A", "target_1": "N/A", "target_2": "N/A",
                "timeframe": "4-8小時", "risk_note": "請手動確認"
            }
        result["symbol"] = symbol
        result["exchange"] = "gemini-flash"
        log.info(f"✅ Gemini 分析{symbol}: {result.get('direction')} {result.get('score')}")
        return result
    except Exception as e:
        log.error(f"Gemini 分析失敗{symbol}: {e}")
        return None

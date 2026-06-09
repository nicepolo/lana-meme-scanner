"""
notify.py – Telegram 推送模組（優化版）
- 信心顯示改為數字：72/100 中信心（對齊網頁格式）
- score >= 65 → 高信心，45-64 → 中信心，< 45 → 低信心
- 推送格式更清晰，方便直接判斷是否入場
"""

import os
import logging
import requests
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

TZ_TAIPEI = timezone(timedelta(hours=8))

DIRECTION_EMOJI = {
    "LONG":  "🟢",
    "SHORT": "🔴",
    "WATCH": "⚪",
}
DIRECTION_TEXT = {
    "LONG":  "做多 ▲",
    "SHORT": "做空 ▼",
    "WATCH": "觀望",
}


def _conf_label(score: int) -> str:
    """把數字分數轉成信心文字標籤"""
    if score >= 65:
        return "高信心 🔥"
    elif score >= 45:
        return "中信心 ✅"
    else:
        return "低信心 ⚠️"


# 防重複推送：記錄最近一次推送的訊號指紋
_last_push_hash = ""
_last_push_time = 0.0

def send_telegram(results: list):
    """批次推送所有達標訊號到 Telegram（含防重複機制）"""
    global _last_push_hash, _last_push_time
    import time, hashlib

    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram 憑證缺失，跳過推送")
        return

    # 計算本輪訊號指紋（symbol+score 組合）
    fingerprint = hashlib.md5(
        ",".join(f"{r.get('symbol')}:{r.get('score')}" for r in results).encode()
    ).hexdigest()

    now_ts = time.time()
    # 同樣的訊號在 10 分鐘內不重複推
    if fingerprint == _last_push_hash and now_ts - _last_push_time < 600:
        log.warning(f"⛔ 偵測到重複推送（指紋相同），略過本輪")
        return

    _last_push_hash = fingerprint
    _last_push_time = now_ts

    now = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M")
    header = f"🐕 *LANA Meme Scanner* | {now}\n"
    header += f"共 {len(results)} 個訊號達標\n"
    header += "─" * 28

    _send_message(header)

    for i, r in enumerate(results, 1):
        msg = _format_signal(i, r)
        _send_message(msg)

    footer = (
        "─" * 28 + "\n"
        "⚠️ *風險提示*\n"
        "訊號僅供參考，需確認後入場。\n"
        "嚴控倉位，設好止損，單筆不超 3-5%。"
    )
    _send_message(footer)


def _format_signal(idx: int, r: dict) -> str:
    direction = r.get("direction", "WATCH")
    d_emoji   = DIRECTION_EMOJI.get(direction, "⚪")
    d_text    = DIRECTION_TEXT.get(direction, "觀望")

    symbol   = r.get("symbol", "?")
    exchange = r.get("exchange", "?").capitalize()
    price    = r.get("price", 0)
    change   = r.get("change_24h", 0)
    score    = r.get("score", 0)
    vol      = r.get("vol_ratio", 1)
    rsi      = r.get("rsi_1h", 50)
    fr       = r.get("funding_rate", None)
    is_major = r.get("is_major", False)

    # 信心標籤
    if score >= 65:
        conf_emoji = "🔥"
        conf_level = "高"
    elif score >= 45:
        conf_emoji = "✅"
        conf_level = "中"
    else:
        conf_emoji = "⚠️"
        conf_level = "低"
    conf_text = _conf_label(score)

    # 資金費率
    if fr is not None:
        fr_pct = fr * 100
        if abs(fr) >= 0.001:
            fr_str = f"  💥 FR: {fr_pct:+.3f}%（極端）"
        elif abs(fr) >= 0.0005:
            fr_str = f"  ❗ FR: {fr_pct:+.3f}%（偏高）"
        else:
            fr_str = f"  FR: {fr_pct:+.3f}%"
    else:
        fr_str = ""

    major_tag   = " 🏆主流幣" if is_major else ""
    change_str  = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
    change_icon = "📈" if change >= 0 else "📉"

    lines = [
        f"{d_emoji} *#{idx} {symbol}/USDT* ({exchange}){major_tag}",
        f"現價: `{price}`  {change_icon} 24h {change_str}",
        f"方向: {d_text}  {conf_emoji}  信心: {conf_level}  訊號強度: {score}/100",
        f"RSI 1H: {rsi:.1f}  量能: {vol:.1f}x{fr_str}",
        "",
        f"📌 *{r.get('summary', '')}*",
        f"_{r.get('reason', '')}_",
        "",
        f"🎯 入場區間: `{r.get('entry_zone', 'N/A')}`",
        f"🛑 止損: `{r.get('stop_loss', 'N/A')}`",
        f"✅ 目標1: `{r.get('target_1', 'N/A')}`",
        f"🏆 目標2: `{r.get('target_2', 'N/A')}`",
        f"⏱ 預期持倉: {r.get('timeframe', 'N/A')}",
        f"⚠️ {r.get('risk_note', '嚴控倉位')}",
    ]

    return "\n".join(lines)


def _send_message(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            log.error(f"Telegram 推送失敗: {r.text}")
    except Exception as e:
        log.error(f"Telegram 連線錯誤: {e}")

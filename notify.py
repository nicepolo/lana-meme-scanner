"""
notify.py — Telegram 推播格式化與發送
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
    "WATCH": "⚪️"
}
DIRECTION_TEXT = {
    "LONG":  "做多 ▲",
    "SHORT": "做空 ▼",
    "WATCH": "觀望"
}
CONF_EMOJI = {"高": "🔥", "中": "✅", "低": "⚠️"}


def send_telegram(results: list):
    """發送完整掃描結果到 Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram 憑證未設定，跳過推播")
        return

    now = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M")
    header = f"🐕 *LANA Meme Scanner* | {now}\n"
    header += f"共 {len(results)} 個訊號達標\n"
    header += "─" * 28

    _send_message(header)

    for i, r in enumerate(results, 1):
        msg = _format_signal(i, r)
        _send_message(msg)

    # 尾部免責聲明
    footer = (
        "─" * 28 + "\n"
        "⚠️ *免責聲明*\n"
        "本訊號僅供參考，非投資建議。\n"
        "土狗幣波動極大，請嚴格控制倉位，\n"
        "每筆不超過總資金 3-5%。"
    )
    _send_message(footer)


def _format_signal(idx: int, r: dict) -> str:
    direction = r.get("direction", "WATCH")
    d_emoji = DIRECTION_EMOJI.get(direction, "⚪️")
    d_text  = DIRECTION_TEXT.get(direction, "觀望")
    conf    = r.get("confidence", "低")
    c_emoji = CONF_EMOJI.get(conf, "⚠️")

    symbol   = r.get("symbol", "?")
    exchange = r.get("exchange", "?").capitalize()
    price    = r.get("price", 0)
    change   = r.get("change_24h", 0)
    score    = r.get("score", 0)
    vol      = r.get("vol_ratio", 1)
    rsi      = r.get("rsi_1h", 50)

    change_str = f"+{change}%" if change >= 0 else f"{change}%"
    change_icon = "📈" if change >= 0 else "📉"

    lines = [
        f"{d_emoji} *#{idx} {symbol}/USDT* ({exchange})",
        f"現價：`{price}`  {change_icon} 24h {change_str}",
        f"方向：{d_text}  {c_emoji} 信心：{conf}  訊號強度：{score}/100",
        f"RSI 1H：{rsi}  量能：{vol}x",
        "",
        f"📌 *{r.get('summary', '')}*",
        f"_{r.get('reason', '')}_",
        "",
        f"🎯 入場區間：`{r.get('entry_zone', 'N/A')}`",
        f"🛑 止損：`{r.get('stop_loss', 'N/A')}`",
        f"✅ 目標1：`{r.get('target_1', 'N/A')}`",
        f"🏆 目標2：`{r.get('target_2', 'N/A')}`",
        f"⏱ 預期持倉：{r.get('timeframe', 'N/A')}",
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
            log.error(f"Telegram 發送失敗: {r.text}")
    except Exception as e:
        log.error(f"Telegram 請求異常: {e}")

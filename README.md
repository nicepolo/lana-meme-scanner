# LANA Meme Scanner v1.0

土狗幣 + LUNA 多空 AI 分析模組，整合 Binance / Bybit / OKX。

## 功能

- 每 15 分鐘自動掃描 10 個 meme 幣
- 多時間框架分析（4H / 1H / 15M）
- 呼叫 Claude AI 分析盤面，給出做多/做空/觀望建議
- Telegram 推播：含入場區間、止損、目標價
- 備用規則式分析（沒有 API Key 也能跑）

## 監控幣種

LUNA / LUNC / DOGE / SHIB / PEPE / FLOKI / BONK / WIF / NEIRO / MEME

## 檔案結構

```
lana-meme-scanner/
├── meme_scanner.py   # 主程式 + 排程
├── exchanges.py      # 三大交易所 K 線抓取
├── indicators.py     # RSI / MACD / 布林通道 / MA
├── ai_analysis.py    # Claude AI 分析核心
├── notify.py         # Telegram 推播格式化
├── requirements.txt
├── Procfile
└── .env.example
```

## 推播格式預覽

```
🐕 LANA Meme Scanner | 2026-06-06 14:30
共 2 個訊號達標
────────────────────────────
🟢 #1 PEPE/USDT (Binance)
現價：0.00001234  📉 24h -8.5%
方向：做多 ▲  ✅ 信心：中  訊號強度：72/100
RSI 1H：34.2  量能：1.8x

📌 超賣反彈機會
技術面接近布林下軌，RSI 超賣，MACD 轉正

🎯 入場區間：0.00001220 - 0.00001234
🛑 止損：0.00001185
✅ 目標1：0.00001290
🏆 目標2：0.00001350
⏱ 預期持倉：4-8小時
⚠️ 土狗幣波動極大，嚴控倉位 ≤3%
```

## 部署到 Railway（新 Worker 服務）

### 方法一：加進現有 repo（推薦）

把這個資料夾的檔案複製到你現有的 LANA repo，推上 GitHub 後：
1. Railway → 你的 LANA project → **New Service** → **GitHub Repo**
2. 選同一個 repo，設定 Root Directory 為 `lana-meme-scanner`
3. Settings → Deploy → Start Command 改為：`python meme_scanner.py`

### 方法二：建立獨立 repo

```bash
cd lana-meme-scanner
git init
git add .
git commit -m "init meme scanner v1"
git remote add origin https://github.com/nicepolo/lana-meme-scanner.git
git push -u origin main
```

Railway → New Project → Deploy from GitHub → 選 repo

### Variables 設定

| 變數 | 必填 | 說明 |
|------|------|------|
| TELEGRAM_BOT_TOKEN | ✅ | 沿用現有 LANA bot |
| TELEGRAM_CHAT_ID | ✅ | 沿用現有 chat id |
| ANTHROPIC_API_KEY | 建議 | Claude AI 分析用 |
| MEME_SCAN_INTERVAL_MIN | — | 預設 15 分鐘 |
| MIN_SCORE_TO_ALERT | — | 預設 60 分 |

## 注意事項

1. **倉位控制**：每個 meme 幣建議不超過總資金 3-5%
2. **訊號強度**：score ≥ 75 才考慮做大倉
3. **土狗幣特性**：可能在 5 分鐘內暴漲暴跌，務必掛好止損
4. **LUNA/LUNC**：流動性較薄，滑點大，謹慎操作

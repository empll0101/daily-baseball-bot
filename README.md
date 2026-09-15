# ⚾ 臺灣棒球旅外球員即時數據追蹤 Bot (Taiwan Baseball Tracker)

一個以 **Discord 私訊 (DM)** 即時推播臺灣旅外球員（美職 MLB、日職 NPB、韓職 KBO）比賽動態與每日成績的 Python 機器人。

每位使用者可獨立設定追蹤名單，支援 **打者逐打席**、**投手逐局**、**終場數據** 即時通知，以及每日定時成績彙整。

---

## 🌟 核心特色

- **三大聯盟支援**：
  - 🇺🇸 **MLB 美國職棒**：串接官方 MLB Stats API，支援球員姓名搜尋、即時 Play-by-play 與完整 Boxscore。
  - 🇯🇵 **NPB 日本職棒**：爬取 Yahoo! JAPAN 賽況數據，內建日文棒球術語中文化字典（`npb_dict.py`），提供逐打席與逐局動態。
  - 🇰🇷 **KBO 韓國職棒**：串接 Naver Sports API 與 KBO 官網，內建臺灣旅韓/測試球員中文譯名對照與韓語賽況翻譯。
- **個人化獨立訂閱**：每位 Discord 使用者最多可訂閱 10 名球員（上限可自訂），各自接收專屬私訊推播。
- **即時事件推播**：
  - 📢 **打席提前預告 (On-Deck)**：追蹤打者的**前一棒**上場時，自動發送「即將上場打擊」預告（標記當前局數與出局數），不漏接關鍵打席。
  - 🎯 **打者動態**：每個完整打席結果（安打、全壘打、保送、三振等），並標註當前對決投手。
  - ⚾ **投手動態**：每個完整打席投球對決結果、半局結束統計，以及**投手退場結算通知**（即時統計投球局數、用球數、三振、四死、失分與自責分）。
  - 🏆 **終場數據**：賽事結束時發送單場詳細成績與本季累計數據。
- **每日定時彙整**：每日台灣時間 23:00 自動統整當日所有訂閱球員的出賽成績並私訊發送，亦可隨時用 `/today` 即時查詢。
- **防重複與補發機制**：使用 SQLite 本地資料庫紀錄推播歷史，重啟後自動補發最近 3 天內的遺漏事件，不重複發送、不捏造缺漏數據。

---

## 🏗️ 系統架構

```
daily-baseball-bot/
├── tracker/
│   ├── __main__.py          # 程式執行入口
│   ├── main.py              # 初始化 Database, ClientSession, Providers, Bot
│   ├── config.py            # 設定檔載入與環境變數驗證
│   ├── models.py            # 資料模型 (League, Player, Subscription, TrackingEvent)
│   ├── database.py          # SQLite 資料庫操作 (subscriptions, events, deliveries, meta)
│   ├── service.py           # 背景輪詢任務 (TrackingService)、事件推播與每日摘要排程
│   ├── bot.py               # Discord Slash Commands (/search, /subscribe, /today...)
│   └── providers/           # 聯盟資料源介面與實作
│       ├── base.py          # DataProvider 抽象類別
│       ├── mlb.py           # MLB Stats API 實作
│       ├── npb.py           # NPB Yahoo! JAPAN 爬蟲實作
│       ├── npb_dict.py      # NPB 術語/守位/局數中文化字典
│       └── kbo.py           # KBO Naver Sports / 官網實作與韓語字典
├── data/
│   └── tracker.db           # SQLite 本地資料庫 (執行時自動建立)
├── tests/                   # 單元測試集 (pytest)
├── .env.example             # 環境變數範本
├── setup.bat                # Windows 一鍵安裝腳本
└── run_bot.bat              # Windows 一鍵啟動腳本
```

---

## 📋 斜線指令 (Slash Commands)

| 指令 | 說明 | 參數範例 |
| :--- | :--- | :--- |
| `/search` | 搜尋球員並取得聯盟 ID | `league: MLB` `name: Lee` |
| `/subscribe` | 依聯盟與球員 ID 訂閱球員 | `league: MLB` `player_id: 660271` `display_name: 大谷翔平` |
| `/subscriptions` | 查看目前個人的訂閱清單 | *(無參數)* |
| `/unsubscribe` | 取消訂閱特定球員 | `league: MLB` `player_id: 660271` |
| `/today` | 立即私訊發送今日所有訂閱球員之出賽摘要 | *(無參數)* |
| `/status` | 檢查機器人運作狀態與各聯盟資料源連線 | *(無參數)* |

> 💡 **球員 ID 取得方式**：
> - **MLB**：直接使用 `/search league:MLB name:<英文姓氏>` 搜尋。
> - **KBO**：直接使用 `/search league:KBO name:<中文或韓文姓名>` 搜尋。
> - **NPB**：前往 [Yahoo! JAPAN プロ野球 個人成績](https://baseball.yahoo.co.jp/npb/) 找到球員頁面，網址中的數字即為 ID（例如 `https://baseball.yahoo.co.jp/npb/player/2103780/top` 的 ID 為 `2103780`）。

---

## 🚀 快速安裝與啟動

### 1. 前置準備
- 安裝 **Python 3.11** 或更高版本 ([官方下載連結](https://www.python.org/downloads/))，安裝時請務必勾選 **"Add Python to PATH"**。
- 前往 [Discord Developer Portal](https://discord.com/developers/applications) 建立 Application 並取得 **Bot Token**。

### 2. Windows 一鍵安裝
1. 雙擊執行 `setup.bat`（自動建立虛擬環境 `.venv`、升級 pip、安裝相依套件並產生 `.env`）。
2. 開啟 `.env` 檔案，將 `DISCORD_TOKEN` 替換為你的 Discord Bot Token：
   ```env
   DISCORD_TOKEN=your_bot_token_here
   ```
3. 雙擊執行 `run_bot.bat` 即可啟動機器人。

### 3. Linux / macOS / 手動指令安裝

```bash
# 1. 建立並啟動虛擬環境
python3 -m venv .venv
source .venv/bin/activate   # Windows PowerShell 請使用: .venv\Scripts\Activate.ps1

# 2. 安裝套件
pip install --upgrade pip
pip install -e ".[dev]"

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env 填入 DISCORD_TOKEN

# 4. 啟動機器人
python -m tracker
```

---

## ⚙️ 環境變數設定 (`.env`)

| 變數名稱 | 預設值 | 說明 |
| :--- | :---: | :--- |
| `DISCORD_TOKEN` | *(必填)* | Discord Bot Token（請勿洩漏或 commit 上 Git） |
| `DATABASE_PATH` | `data/tracker.db` | SQLite 資料庫存放路徑 |
| `POLL_INTERVAL_SECONDS` | `120` | 比賽資料輪詢間隔（秒），最低不可小於 30 秒 |
| `DAILY_SUMMARY_HOUR` | `23` | 每日摘要發送時間（小時，台灣時間 0~23） |
| `DAILY_SUMMARY_MINUTE`| `0` | 每日摘要發送時間（分鐘，0~59） |
| `MAX_SUBSCRIPTIONS` | `10` | 每個使用者最多可訂閱的球員數量 |
| `BACKFILL_DAYS` | `3` | 重啟後補發最近幾天內的賽事事件 |
| `LOG_LEVEL` | `INFO` | 日誌等級 (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 🤖 如何讓朋友使用此機器人？

你可以選擇以下兩種方式分享給朋友：

### 方法 A：由你託管機器人，朋友加入使用（最推薦）
1. **設定 Discord Bot 安裝權限**：
   - 進入 [Discord Developer Portal](https://discord.com/developers/applications) -> 點選你的 Application -> 進入 **Installation** 分頁。
   - 在 **Installation Contexts** 勾選 **Guild Install**（安裝到伺服器）或 **User Install**（使用者安裝到個人帳號）。
   - 在 **Default Install Purchase / Scopes** 勾選 `bot` 與 `applications.commands`。
   - 下方的 **Install Link** 選擇 *Discord Provided Link*，即可複製專屬邀請安裝連結。
2. **分享給朋友**：
   - 把邀請連結傳給朋友，或把機器人邀請到你與朋友共同所在的 Discord 伺服器中。
3. **重要設定（私訊接收）**：
   - 提醒朋友檢查 Discord 設定：**「使用者設定」->「隱私與安全」-> 允許「來自伺服器成員的私人訊息」**（因為通知是以 Bot 私訊 DM 發送）。
4. **開始使用**：
   - 朋友在伺服器或私聊中輸入 `/search` 或 `/subscribe` 即可建立個人化追蹤清單！

### 方法 B：朋友自行架設專屬機器人
- 朋友只需 Clone 本專案，依照 [快速安裝與啟動](#-快速安裝與啟動) 填寫他自己的 Bot Token 即可獨立運行。

---

## 🧪 執行測試

本專案使用 `pytest` 進行單元測試（涵蓋 MLB / NPB / KBO 資料解析器、SQLite 資料庫與每日摘要格式化）：

```bash
# Windows
.\.venv\Scripts\python.exe -m pytest

# Linux / macOS
pytest
```

---

## 📝 授權與免責聲明

- 本專案僅供個人學習與非商業性質之球迷數據追蹤使用。
- 各聯盟賽事數據與球員商標版權分別歸屬 MLB Advanced Media、NPB、KBO 及各資料提供平台所有。

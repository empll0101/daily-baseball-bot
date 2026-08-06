# 臺灣球員每日數據追蹤

以 Discord 私訊追蹤指定旅外球員成績的 Python MVP。目前 MLB 已接上免費的
MLB Stats API；NPB、KBO 已保留訂閱、資料源介面與降級告警，但尚未找到同時
滿足「免費、10 分鐘內、逐打席／逐局、可補發三天」的穩定資料源，因此不會
假裝提供資料。

## 現有功能

- 每位 Discord 使用者獨立訂閱，最多 10 人
- `/search` 搜尋 MLB 球員，或以 `/subscribe` 手動輸入三聯盟球員 ID
- MLB 打者每個完整打席、投手每個完整半局通知
- MLB 終場單場數據與球季累計
- SQLite 防止重複通知，保留重啟後的補發進度
- 台灣時間 23:00 每日私訊摘要，以及 `/today` 手動查詢
- 資料源失效時每日最多一次告警，不捏造缺漏數據

## Windows 安裝

1. 安裝 Python 3.11 或更新版本。
2. 雙擊 `setup.bat`。
3. 到 [Discord Developer Portal](https://discord.com/developers/applications) 建立
   Application 與 Bot，取得 Token。Token 是密碼，不要貼到聊天或提交 Git。
4. 編輯 `.env`，將 `DISCORD_TOKEN` 改為你的 Token。
5. 在 Developer Portal 的 Installation 頁啟用 User Install，scope 選
   `applications.commands`；用安裝連結把 App 安裝到自己的 Discord 帳號。
6. 雙擊 `run_bot.bat`。視窗必須保持開啟。

## 指令

- `/search league name`：搜尋球員並取得 ID
- `/subscribe league player_id display_name`：訂閱球員
- `/subscriptions`：查看訂閱名單
- `/unsubscribe league player_id`：取消訂閱
- `/today`：立即把今日摘要傳到私訊
- `/status`：查看資料源狀態

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 資料與補發規則

資料保存在 `data/tracker.db`。輪詢預設每兩分鐘一次。系統只補發最近三天內可
取得的逐事件資料；更早事件不補逐打席／逐局。免費來源若只有終場資料，僅發
逐場摘要並清楚標示。23:00 摘要依台灣日期切分，尚未結束的比賽留至隔日。

## 已知限制

- NPB、KBO 尚無已驗證資料源，現階段訂閱後只會收到降級告警。
- MLB 投手「逐局」數字由該半局 play-by-play 彙整；官方若事後改判自責分，請
  以終場 box score 為準。
- 公開免費 API 沒有 SLA，端點或欄位可能變動。

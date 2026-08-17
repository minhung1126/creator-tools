# YouTube Data API 配額

Creator Tools 會依每個 YouTube OAuth 授權組合保存請求層級的配額估算。這是本機 ledger，不是 Google Cloud Console 的即時專案總用量，也不包含其他應用程式送出的請求。

## 官方基準與本專案使用的成本

Google 官方目前說明：YouTube Data API 專案對搜尋、影片上傳等方法另有每日限制；其他端點合計的預設配額為每日 10,000 單位。官方配額可能調整，正式設定仍應以 Google Cloud Console 為準。

本專案目前登記的請求成本如下：

| API 方法 | 每次請求單位 | 用途 |
| --- | ---: | --- |
| `playlistItems.list` | 1 | 讀取 To-Post 播放清單 |
| `videos.list` | 1 | 讀取影片資訊 |
| `videos.update` | 50 | 更新影片資訊或公開狀態 |
| `playlistItems.delete` | 50 | 從播放清單移除影片 |
| `channels.list` | 1 | OAuth 頻道驗證 |
| `playlists.list` | 1 | 上傳前驗證共用 To-Post |
| `playlistItems.insert` | 50 | 將影片加入共用 To-Post |

Drive 上傳另有獨立的 `video_uploads` bucket：`videos.insert` 每部預設計 1 unit，每個 slot 預設每日 100 部。這個 bucket 與 General ledger 分開保存：`data/youtube_quota_uploads_usage.json`、`data/youtube_quota_uploads_usage.secondary.json`。

每取得一頁資料就會算一次請求成本。即使請求無效，官方也規定至少會消耗一個配額單位。

官方資料：

- [YouTube Data API 配額成本](https://developers.google.com/youtube/v3/determine_quota_cost)
- [YouTube Data API 概覽與預設配額](https://developers.google.com/youtube/v3/getting-started)
- [YouTube Data API 錯誤，包含 quotaExceeded](https://developers.google.com/youtube/v3/docs/errors)
- [Google Cloud 配額檢視與管理](https://cloud.google.com/docs/quotas/view-manage)

## Creator Tools 的保護邏輯

- 每個授權組合各自使用一份 ledger：`primary` 為 `data/youtube_quota_usage.json`，`secondary` 為 `data/youtube_quota_usage.secondary.json`。
- 請求送出前先保留官方成本；安全預留會從專案可用上限扣除。若預估會超過安全上限，請求不會送出。
- 系統預設專案配額為 10,000 單位，安全預留預設為 1,000 單位；登入後可在 YouTube 設定頁按授權組合調整。
- Google 回傳 HTTP 403 且錯誤原因為 `quotaExceeded` 時，該授權組合會標記為已確認用完，新的請求會停止，直到官方重設。
- Auto routing 會在新的 workflow 開始時優先檢查 Primary；若本次保守成本無法由 Primary 的安全可用額度支應，會選用 Secondary。這不是同一批次中途重試，已開始的 workflow 會固定原本選定的 slot。
- Drive 上傳預覽會同時檢查 `video_uploads` 與 General 兩個 bucket；工作建立後固定同一個 slot，不會因 quota 變化中途換 slot。每部影片只在取得 YouTube ID 後才保存為已上傳，重試時已有 ID 的項目只重試 playlist insertion。
- `quotaExceeded` 或本地安全上限只會封鎖目前 slot；下一個 workflow 會重新評估，Primary 恢復且足夠時會再次優先使用 Primary。
- YouTube 設定也支援手動模式；手動模式只使用目前作用中的 slot，不會自動 fallback。
- 配額日界線依 `America/Los_Angeles` 的午夜計算；前端同時顯示 Pacific Time 與瀏覽器本地時間。

## 與寫入流程的關係

批次覆寫與「公開並清理 To-Post」都先建立完整預覽。預覽由後端以帳號、實際選定的 YouTube slot、播放清單／試算表快照與影片目前 metadata 簽署；執行時會沿用預覽所選 slot，避免 Primary 在兩次 request 之間恢復而改變授權組合。執行前若任一項變更，API 回傳 `409 stale_preview`，不會寫入任何影片或播放清單項目。配額不足則保留已完成項目的結果，未執行項目標示為「未執行」；重新建立下一個 workflow 時才會重新選擇 slot。

YouTube 設定頁的預設播放清單與 quota 是兩個獨立儲存動作：播放清單使用 `/settings/youtube/playlist`，quota 使用 `/settings/youtube/quota`。舊的合併寫入端點會拒絕請求，避免未儲存草稿互相覆蓋。

請持續保存整個 `data/` volume，否則會遺失配額 ledger、session、帳號工作狀態與加密憑證。

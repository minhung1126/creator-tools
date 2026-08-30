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
- Google 回傳 HTTP 403 且錯誤原因為 `quotaExceeded`、`dailyLimitExceeded` 或 `dailyLimitExceededUnreg` 時，該授權組合會標記為已確認用完，新的請求會停止，直到官方重設。
- Auto routing 會在新的 workflow 開始時優先檢查 Primary；若本次保守成本無法由 Primary 的安全可用額度支應，會選用 Secondary。若執行途中 provider 或本地 ledger 回報 quota 不足，Auto 模式會在安全的單一操作邊界切換另一個 slot 並重試，不需要使用者重新按兩次。
- Drive 上傳預覽會同時檢查 `video_uploads` 與 General 兩個 bucket；工作建立後先使用預選 slot，執行途中 quota 失敗時會自動切換另一個已驗證同頻道的 slot。每部影片只在取得 YouTube ID 後才保存為已上傳，重試時已有 ID 的項目只重試 playlist insertion。
- Drive 上傳完整流程的 General 保守成本是 `2 + 50 × insertion_count`：預覽時一次 `playlists.list`、建立工作前再驗證一次，之後每個 To-Post 插入各 50 單位；`video_uploads` 則只計 `1 × new_upload_count`。因此 resume-only 工作（`new_upload_count = 0`）不會誤扣 `video_uploads`。
- 上傳預覽回傳的 `quota.preview_read`、`quota.job_required`、`quota.total` 與 `quota.create_can_execute` 是分階段契約；前端必須依 `job_required` 與兩個 bucket 的可用量判斷是否能建立工作，不可把已花費的預覽讀取再次加總。建立工作時仍會重新驗證 quota、slot、Drive snapshot 與播放清單。
- 若 playlist insertion 的回應中斷，工作會保存已取得的 YouTube ID，重試前先以 `playlistItems.list` reconciliation 尋找既有項目，找到時不會重複插入；該 reconciliation 讀取也會經過 General quota ledger，配額不足時工作會安全暫停。
- `quotaExceeded` 或本地安全上限只會封鎖目前 slot；目前 Auto workflow 會先嘗試另一個 slot，兩個 slot 都不可用時才暫停或回傳 quota 錯誤。下一個 workflow 仍會重新評估，Primary 恢復且足夠時會再次優先使用 Primary。
- YouTube 設定也支援手動模式；手動模式只使用目前作用中的 slot，不會自動 fallback。
- 配額日界線依 `America/Los_Angeles` 的午夜計算；前端同時顯示 Pacific Time 與瀏覽器本地時間。

## 與寫入流程的關係

批次覆寫與「公開並清理 To-Post」都先建立完整預覽。預覽由後端以帳號、實際選定的 YouTube slot、播放清單／試算表快照與影片目前 metadata 簽署；執行時優先沿用預覽所選 slot，若 Auto 模式在寫入邊界遇到 quota 不足，會驗證同頻道的另一 slot 後重試目前操作。執行前若任一項變更，API 回傳 `409 stale_preview`，不會寫入任何影片或播放清單項目。兩個 slot 都不足時才保留已完成項目的結果，未執行項目標示為「未執行」。

YouTube 設定頁的預設播放清單與 quota 是兩個獨立儲存動作：播放清單使用 `/settings/youtube/playlist`，quota 使用 `/settings/youtube/quota`。舊的合併寫入端點會拒絕請求，避免未儲存草稿互相覆蓋。

請持續保存整個 `data/` volume，否則會遺失配額 ledger、session、帳號工作狀態與加密憑證。

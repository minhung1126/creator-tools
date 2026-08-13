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
- `quotaExceeded` 不會自動改用另一個授權組合，也不會建立背景重試工作。
- 配額日界線依 `America/Los_Angeles` 的午夜計算；前端同時顯示 Pacific Time 與瀏覽器本地時間。

## 與寫入流程的關係

批次覆寫與「公開並清理 To-Post」都先建立完整預覽。預覽由後端以帳號、作用中 YouTube slot、播放清單／試算表快照與影片目前 metadata 簽署；執行前若任一項變更，API 回傳 `409 stale_preview`，不會寫入任何影片或播放清單項目。配額不足則保留已完成項目的結果，未執行項目標示為「未執行」，不會自動跨 slot 重試。

YouTube 設定頁的預設播放清單與 quota 是兩個獨立儲存動作：播放清單使用 `/settings/youtube/playlist`，quota 使用 `/settings/youtube/quota`。舊的合併寫入端點會拒絕請求，避免未儲存草稿互相覆蓋。

## 與寫入流程的關係

批次覆寫與「公開並清理 To-Post」都先建立完整預覽。預覽由後端以帳號、作用中 YouTube slot、播放清單／試算表快照與影片目前 metadata 簽署；執行前若任一項變更，API 回傳 `409 stale_preview`，不會寫入任何影片或播放清單項目。配額不足則保留已完成項目的結果，未執行項目標示為「未執行」，不會自動跨 slot 重試。

YouTube 設定頁的預設播放清單與 quota 是兩個獨立儲存動作：播放清單使用 `/settings/youtube/playlist`，quota 使用 `/settings/youtube/quota`。舊的合併寫入端點會拒絕請求，避免未儲存草稿互相覆蓋。

請持續保存整個 `data/` volume，否則會遺失配額 ledger、session、帳號工作狀態與加密憑證。

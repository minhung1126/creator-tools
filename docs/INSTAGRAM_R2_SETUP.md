# Instagram Reels API、Instagram Login 與 Cloudflare R2 設定教學

Creator Tools 使用 Instagram API with Instagram Login。Instagram 專業帳號不必連結 Facebook 粉絲專頁。

## 1. Meta App 與 OAuth

Creator Tools 使用 **Instagram API with Instagram Login**（Business Login for Instagram），不是舊的 Instagram Basic Display，也不是 Facebook Login for Business 的登入流程。

### 1.1 進入 Instagram API 設定

Meta 後台的畫面會因語言與版本不同而略有差異，請依下列路徑操作：

1. 開啟 [Meta for Developers](https://developers.facebook.com/apps/)，進入「我的應用程式」，選擇 Creator Tools 使用的 App。
2. 建立 App 時應選擇可使用 Instagram API 的 Business 應用程式／使用案例。
3. 在 App 的使用案例或產品清單中找到 **Instagram API**，按 **「編輯」** 進入設定。若目前顯示的是「自訂使用案例」，請在左側選單選取 **Instagram API**，再選 **「含有 Instagram 登入的 API 設定」**。
4. 進入後確認頁面包含 **Instagram 應用程式編號**、**Instagram 應用程式密鑰**，以及 **含有 Instagram 登入的 API 設定**。不要只在「商家專用 Facebook 登入」的設定頁填入 URI；那是另一套 OAuth 流程。

### 1.2 設定 OAuth Redirect URI

在 Instagram API 設定頁的 OAuth／Business login settings 中，找到 **Valid OAuth Redirect URIs**，新增下列網址：

```text
{PUBLIC_BASE_URL}/api/v1/instagram/auth/callback
```

例如正式環境：

```text
https://creator-tools.ymin.io/api/v1/instagram/auth/callback
```

本機環境：

```text
http://localhost:8000/api/v1/instagram/auth/callback
```

URI 必須逐字一致：不可多加結尾 `/`、查詢參數或 `#fragment`。畫面上的「重新導向 URI 驗證程式」只能用來檢查 URI；實際設定仍要在 Instagram API 的 OAuth settings 中儲存。

### 1.3 設定憑證、權限與測試帳號

- Instagram 帳號必須是 Business 或 Creator 專業帳號。
- 從同一個 Instagram API 設定頁的 **Instagram 應用程式編號／密鑰** 取得憑證，填入 `INSTAGRAM_APP_ID` 與 `INSTAGRAM_APP_SECRET`。不要混用另一個 App 或 Facebook Login 流程的憑證。
- 在「含有 Instagram 登入的 API 設定」第 1 步按 **Go to permissions and features**，確認至少啟用：
  - `instagram_business_basic`
  - `instagram_business_content_publish`
- `instagram_business_manage_comments` 與 `instagram_business_manage_messages` 不是本專案發布 Reels 的必要權限；只有使用留言或訊息功能時才需要。
- 若權限清單沒有 `instagram_business_content_publish`，目前只能完成登入／讀取基本資料，不能使用本專案的 Reels 發布功能。
- Development Mode 下，把要連線的 Instagram 帳號加入測試角色，並接受 Meta 發出的邀請。
- 在 Instagram API 設定第 2 步按 **新增帳號**，把要測試的專業帳號加入／指定給 App；之後使用該帳號重新授權。
- 第 3 步的 Webhooks 不是本專案 Reels 發布流程的必要條件；只有要接收留言、訊息或其他事件通知時才需要設定。
- 若只服務自己管理且已加入 App Dashboard 的帳號，通常可使用 Standard Access；若要服務不屬於自己管理的其他帳號，請依 Meta 後台要求申請 Advanced Access／App Review。
- 修改 `.env` 後必須重啟後端，設定才會生效。

```env
INSTAGRAM_APP_ID=你的 App ID
INSTAGRAM_APP_SECRET=你的 App Secret
PUBLIC_BASE_URL=https://creator.example.com
FRONTEND_URL=https://creator.example.com
ALLOWED_GOOGLE_EMAILS=admin@example.com
CREDENTIAL_ENCRYPTION_KEY=固定且足夠長的隨機字串
```

Instagram API version 目前由後端固定為 `v25.0`，不能由 UI 任意修改；callback 只由 `PUBLIC_BASE_URL` 產生。版本定義位於 `backend/app/core/config.py`。

完成 OAuth 後，Token 會加密存於 `data/credential_store.json`，不會回傳前端或放在 URL。Meta 沒有回傳 permissions 時，設定頁顯示「未提供／尚未驗證」，不會自行宣稱 required scopes 已授權。

## 2. Cloudflare R2

1. 建立 R2 bucket 與限制於該 bucket 的 Object Read & Write S3 API token。
2. 在 Instagram / R2 設定頁輸入 Account ID、Access Key ID、Bucket Name、HTTPS public base URL 與 Secret Access Key。R2 設定只從登入後的網頁保存，不放在 `.env`。
3. Secret Access Key 只能由 UI 輸入並加密存入 credential store，不支援 env/UI 雙來源。
4. public base URL 必須 HTTPS，系統會拒絕 localhost/private IP；建議使用 Custom Domain 或 `r2.dev`。
5. 為 `instagram-reels/` prefix 設定 1–7 天 lifecycle，預設工作流程使用 3 天，避免影片永久堆積。

Reel 成功發布後，工作流程會立即刪除該支影片的 R2 object；lifecycle 仍作為清理失敗或中斷工作的後備保護。若刪除暫時失敗，工作會保留 `published` 狀態並提供重試清理，不會重複發布 Instagram 影片。

Endpoint：

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

## 3. Reels 工作流程

Drive list 使用 pagination 與 `videoMediaMetadata` 做 size、duration、dimensions preflight。發布工作透過：

```text
POST /api/v1/instagram/publish-jobs
GET  /api/v1/instagram/publish-jobs/{id}
POST /api/v1/instagram/publish-jobs/{id}/retry
```

每片會保存 `queued`、`uploaded`、`container_created`、`published`、`failed`、`paused` 與 creation/media ID。第一片失敗會暫停後續；retry 會沿用已保存的 creation ID。結果保存於 `data/instagram_publish_jobs.json`。

目前發布工作會先拒絕超過 1 GB 或超過 90 秒的影片；90 秒是本專案的流程限制，不代表 Instagram API 的所有媒體規格上限。

Sheet 至少包含：

```text
所屬團體 | 人 | Instagram Caption
```

## 4. 常見問題

- redirect_uri 不相符：確認 Meta 後台與設定頁顯示值逐字一致。
- `Invalid platform app`：先確認已在 App 中按「編輯」進入 Instagram API，而不是只設定「商家專用 Facebook 登入」；再確認 `INSTAGRAM_APP_ID`／`INSTAGRAM_APP_SECRET` 來自同一個 Instagram Login App，且後端已重啟。
- 無法發布或缺少權限：進入「含有 Instagram 登入的 API 設定」→ **Go to permissions and features**，確認清單中有 `instagram_business_content_publish`；截圖中只有 basic、comments、messages 時，尚未完成 Reels 發布所需設定。
- 看不到 Instagram API 或 Business login settings：回到 App 的使用案例／產品清單，將 Instagram API 加入或按「編輯」完成設定；不需要先重建 App。
- 無法解密憑證：確認 `CREDENTIAL_ENCRYPTION_KEY` 沒有被更換。
- R2 抓不到影片：確認 public URL 可在無 Cookie、無 Authorization 的情況下下載。
- 真實帳號驗收前，請先完成 App ID、App Secret、Redirect URI 與測試帳號設定；自動測試只使用 mock。

# Instagram Reels API、Instagram Login 與 Cloudflare R2 設定教學

Creator Tools 使用 Instagram API with Instagram Login。Instagram 專業帳號不必連結 Facebook 粉絲專頁。

Creator Tools 使用 **Instagram API with Instagram Login**（Business Login for Instagram），不是舊的 Instagram Basic Display，也不是 Facebook Login for Business 的登入流程。

> **部署時先看本節。** Meta 後台有多個名稱很像的產品和網址欄位；本專案只使用 **Instagram API → 含有 Instagram 登入的 API 設定**。不要把 URI 填到「商家專用 Facebook 登入」或「Webhooks」欄位。

## 0. 名稱與設定位置對照

### 0.1 Meta、App、Instagram API、Facebook Login 的差異

| 名稱 | 它是什麼 | 本專案是否使用 |
| --- | --- | --- |
| **Meta for Developers** | 管理 App、權限、測試帳號和產品的網站 | 使用 |
| **Meta App** | 應用程式容器；可以包含多個產品／使用案例 | 使用同一個 App，但只使用 Instagram Login |
| **Instagram API with Instagram Login** | Instagram 專業帳號直接登入授權；使用 Instagram User access token | **使用** |
| **Instagram API with Facebook Login** | 先以 Facebook 登入，通常透過 Facebook Page 取得 Instagram 資源 | 不使用 |
| **Facebook Login for Business／商家專用 Facebook 登入** | Facebook 的另一套 OAuth 產品，有自己的 URI 設定 | **不使用** |
| **Instagram Basic Display** | 舊的個人帳號／基本資料流程 | 不使用 |
| **Webhooks** | Meta 主動通知留言、訊息等事件的伺服器回呼 | Reels 發布目前不需要 |

本專案的程式流程是：

```text
www.instagram.com/oauth/authorize
        ↓
api.instagram.com/oauth/access_token
        ↓
graph.instagram.com
```

因此，App ID、App Secret、權限和 OAuth URI 必須設定在 **Instagram API with Instagram Login**。Facebook Login 的設定即使填入相同網址，也不會替代 Instagram Login 的設定。兩套流程使用的 host、token 類型和權限名稱也不同；官方 Meta API 文件將兩套流程分開列出。[Meta Instagram API 文件](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)

### 0.2 三種「回呼／URI」不能混用

| Meta 後台欄位 | 用途 | Creator Tools 的設定 |
| --- | --- | --- |
| **Set up Instagram business login → Redirect URL／Valid OAuth Redirect URIs** | 使用者完成 Instagram 授權後，瀏覽器回到本系統 | `{PUBLIC_BASE_URL}/api/v1/instagram/auth/callback` |
| **Webhooks → Callback URL／回呼網址** | Meta 發生留言、訊息等事件時，伺服器接收通知 | 本專案目前不用，請留空 |
| **商家專用 Facebook 登入 → 設定 → Valid OAuth Redirect URIs** | Facebook Login for Business 的 OAuth callback | 本專案不用，不要只填這裡 |

你之前的截圖是在「商家專用 Facebook 登入 → 設定」頁面；該欄位本身不是填法錯，而是產品不同。必須再到 Instagram API 的 **Set up Instagram business login** 設定一次。

## 1. Meta App 與 OAuth

### 1.1 進入 Instagram API 設定

Meta 後台的畫面會因語言與版本不同而略有差異，請依下列路徑操作：

1. 開啟 [Meta for Developers → My Apps](https://developers.facebook.com/apps/)，進入「我的應用程式」，選擇 Creator Tools 使用的 App。
2. 若新建 App，選擇可使用 Instagram API 的 Business／內容管理使用案例。
3. 進入 App 後，選擇左側的 **使用案例（Use cases）**，或點擊左上方的產品下拉選單。
4. 在產品下拉選單選 **Instagram API**，不要選 **商家專用 Facebook 登入（Facebook Login for Business）**。
5. 在左側選擇：

   ```text
   含有 Instagram 登入的 API 設定
   API setup with Instagram Login
   ```

6. 正確頁面應看到 Instagram 圖示、Instagram 應用程式名稱／編號／密鑰，以及第 1、2、3 步設定區塊。若左上方產品顯示「商家專用 Facebook 登入」，請先切換產品。

> Meta 介面語言和版面會變動；請以 **Instagram API**、**API setup with Instagram Login**、**Set up Instagram business login** 這些關鍵字判斷，不要只依靠左側中文名稱。

### 1.2 設定 OAuth Redirect URI

在正確的 Instagram API 設定頁，展開第 2 步 **產生存取權（Generate access tokens）**。如果頁面出現 **Set up Instagram business login／設定 Instagram business login**，點擊 **Set up／設定**，在跳出的視窗中填入 **Redirect URL／Valid OAuth Redirect URIs**：

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

URI 必須逐字一致：不可多加結尾 `/`、查詢參數或 `#fragment`。畫面上的「重新導向 URI 驗證程式」只能用來檢查 URI；實際設定仍要在 **Instagram API → Set up Instagram business login** 中儲存。

若只看到第 1 步權限、第 2 步存取權和第 3 步 Webhooks，請先展開第 2 步並往下查看。**不要把這個 URI 填到第 3 步 Webhooks 的「回呼網址」**，也不要只填到「商家專用 Facebook 登入 → 設定」。

### 1.2.1 URI 精確比對規則

以下兩個 URI 是不同值：

```text
https://creator-tools.ymin.io/api/v1/instagram/auth/callback
https://creator-tools.ymin.io/api/v1/instagram/auth/callback/
```

請確認：

- `https://` 與 `http://` 不可混用。
- 網域不可混用 `www`、裸網域或其他子網域。
- port 不可省略或自行增加。
- path 必須完全是 `/api/v1/instagram/auth/callback`。
- 不要加最後的 `/`、query string 或 `#fragment`。
- 不要把 Instagram 登入頁、前端首頁或 Webhooks URL 當成 OAuth Redirect URI。

### 1.3 設定憑證、權限與測試帳號

- Instagram 帳號必須是 Business 或 Creator 專業帳號。
- 從同一個 Instagram API 設定頁的 **Instagram 應用程式編號／密鑰** 取得憑證，填入 `INSTAGRAM_APP_ID` 與 `INSTAGRAM_APP_SECRET`。不要混用另一個 App 或 Facebook Login 流程的憑證。
- 在「含有 Instagram 登入的 API 設定」第 1 步按 **Go to permissions and features**，確認至少啟用：
  - `instagram_business_basic`
  - `instagram_business_content_publish`
- `instagram_business_manage_comments` 與 `instagram_business_manage_messages` 不是本專案發布 Reels 的必要權限；只有使用留言或訊息功能時才需要。
- 若權限清單沒有 `instagram_business_content_publish`，目前只能完成登入／讀取基本資料，不能使用本專案的 Reels 發布功能。
- Development Mode 下，先在 **應用程式角色（App roles）→ 角色（Roles）** 將要連線的 Instagram 帳號加入 **Instagram Tester／Instagram 測試人員**，並接受邀請。
- 接著在 Instagram API 設定第 2 步按 **新增帳號（Add account）**，把相同的專業帳號加入／指定給 App。
- 測試帳號必須在 Instagram 端接受邀請：**設定 → 網站權限／Website permissions → 應用程式和網站／Apps and Websites → Tester Invites → Accept**。只有在 Meta 後台新增角色，不代表 Instagram 帳號已完成授權。
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

### 1.4 執行中的 URI 驗證

登入 Google 後，開啟 Creator Tools 的 Instagram 設定頁，頁面會顯示：

```text
Meta 後台 Valid OAuth Redirect URI 必須完全等於：...
```

以這個執行中頁面顯示的值為準，不要只看本機 `.env`。後端也提供：

```text
GET /api/v1/instagram/auth/status
```

正式環境應回傳類似：

```json
{
  "redirect_uri": "https://creator-tools.ymin.io/api/v1/instagram/auth/callback"
}
```

此 endpoint 需要 Google 登入 Session，但可用來確認實際部署的 callback，而不是猜測 Meta 後台應填什麼。

### 1.5 正式部署 `.env` 對照

```env
BIND_HOST=0.0.0.0
PORT=8000
PUBLIC_BASE_URL=https://creator-tools.ymin.io
FRONTEND_URL=https://creator-tools.ymin.io

SECRET_KEY=唯一且隨機的長字串
CREDENTIAL_ENCRYPTION_KEY=固定保存、不要更換的加密金鑰
ALLOWED_GOOGLE_EMAILS=admin@example.com

GOOGLE_CLIENT_ID=你的 Google OAuth Client ID
GOOGLE_CLIENT_SECRET=你的 Google OAuth Client Secret

INSTAGRAM_APP_ID=Instagram API with Instagram Login 頁面上的 Instagram App ID
INSTAGRAM_APP_SECRET=Instagram API with Instagram Login 頁面上的 Instagram App Secret
```

| `.env` | 作用 | 不要混淆成 |
| --- | --- | --- |
| `BIND_HOST` | 容器內監聽位址 | 公開 callback 網域 |
| `PORT` | 容器內服務 port | `PUBLIC_BASE_URL` 的 port |
| `PUBLIC_BASE_URL` | Google／Instagram callback 的來源 | `FRONTEND_URL` 或 localhost |
| `FRONTEND_URL` | OAuth 完成後回到哪個前端頁面 | Instagram OAuth Redirect URI |
| `INSTAGRAM_APP_ID` | Instagram Login client ID | Facebook Login App ID |
| `INSTAGRAM_APP_SECRET` | Instagram Login client secret | Facebook Page access token |
| `CREDENTIAL_ENCRYPTION_KEY` | 加密已儲存 token | 可隨意更換的暫存值 |

修改 `.env` 後必須重新拉取／重啟 production container：

```powershell
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail 100 creator-tools
```

### 1.6 部署前檢查清單

- [ ] Meta App 使用 **Instagram API with Instagram Login**。
- [ ] 左側產品不是 **商家專用 Facebook 登入**。
- [ ] 已啟用 `instagram_business_basic`。
- [ ] 已啟用 `instagram_business_content_publish`。
- [ ] 已在 **Set up Instagram business login** 的 Redirect URL 設定 callback。
- [ ] callback 完全等於 `https://creator-tools.ymin.io/api/v1/instagram/auth/callback`。
- [ ] 沒有把 callback 只填在 Facebook Login 或 Webhooks。
- [ ] `.env` 的 App ID／Secret 來自同一個 Instagram Login App。
- [ ] Instagram 帳號是 Business／Creator。
- [ ] Instagram 帳號已加入測試角色、已接受邀請，並已在第 2 步新增帳號。
- [ ] `.env` 修改後 container 已重啟。
- [ ] Creator Tools 設定頁顯示的 URI 與 Meta 完全一致。
- [ ] 每次測試都重新產生 OAuth URL，不使用舊分頁或舊網址。

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

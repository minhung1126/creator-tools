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

本專案的 R2 用途是暫存從 Google Drive 下載的 Reel，讓 Instagram Graph API 可以透過公開 HTTPS URL 讀取影片。R2 上傳使用 S3-compatible API；Instagram 讀取使用 `r2_public_base_url` 組出的公開物件 URL。

官方文件：

- [Cloudflare R2 總覽](https://developers.cloudflare.com/r2/)
- [R2 S3 API 快速開始](https://developers.cloudflare.com/r2/get-started/s3/)
- [R2 API Token 與權限](https://developers.cloudflare.com/r2/api/tokens/)
- [公開 Bucket 與 Custom Domain](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [R2 CORS](https://developers.cloudflare.com/r2/buckets/cors/)
- [Object lifecycle](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)

### 2.1 建立前先準備

請先準備：

- Cloudflare 帳號，且已啟用 R2。第一次使用 R2 時可能需要先完成付款方式或方案設定，才能建立 API Token。
- 一個由本專案專用的 R2 bucket，例如 `creator-tools-reels`。Bucket 名稱在帳號內必須唯一。
- 一個公開 HTTPS 網域，例如 `https://r2.example.com`。正式環境建議使用自己的 Custom Domain；`r2.dev` 僅適合開發或短期測試。
- 一個只給本專案使用的 R2 API credential。不要把 Cloudflare Global API Key、Cloudflare 登入密碼或其他服務的 API Token 填到 R2 Access Key 欄位。

本專案的 R2 設定欄位與用途如下：

| Creator Tools 欄位 | Cloudflare 對應值 | 用途 |
| --- | --- | --- |
| `R2 Account ID` | Cloudflare 帳號的 Account ID | 組成 S3 endpoint |
| `R2 Access Key ID` | R2 API Token 產生的 Access Key ID | S3 API 登入識別 |
| `R2 Secret Access Key` | 建立 Token 後只顯示一次的 Secret Access Key | S3 API 私密驗證 |
| `R2 Bucket 名稱` | 建立的 bucket 名稱 | 上傳、刪除與 lifecycle 目標 |
| `R2 公開網址／Custom Domain` | 已連到 bucket 的 HTTPS 根網址 | 讓 Instagram 讀取影片 |

### 2.2 建立 R2 Bucket

1. 開啟 [Cloudflare Dashboard](https://dash.cloudflare.com/)，進入 **Storage & databases → R2 → Overview**。
2. 選擇 **Create bucket**。
3. 輸入 bucket 名稱，例如：

   ```text
   creator-tools-reels
   ```

4. Location 可依帳號與資料所在地需求選擇；未使用 jurisdiction-specific bucket 時，本專案的 S3 region 使用 `auto`。
5. 選擇建立。
6. 記下 bucket 名稱，之後必須逐字填入 Creator Tools 的 **R2 Bucket 名稱**。

不要在 bucket 根目錄放置需要永久保存的資料。本專案會使用以下 object key prefix：

```text
instagram-reels/YYYY/MM/DD/...
```

### 2.3 建立 R2 S3 API Token

R2 Access Key 不是一般 Cloudflare API Token。請依 Cloudflare 的 R2 API Token 流程建立：

1. 在 **R2 → Overview** 的 **Account Details** 區塊，按 **Manage**（API Tokens）。
2. 選擇 **Create Account API token**。若要綁定個人 Cloudflare 使用者生命週期，也可以選 **Create User API token**，但使用者被移除帳號後該 Token 會失效。
3. 權限至少要能對指定 bucket 進行物件的讀取、寫入與列出；在 Cloudflare 介面通常選 **Object Read & Write**，並選 **Apply to specific buckets only**，只勾選本專案的 bucket。
4. 為目前程式的自動 lifecycle 設定確認額外的 bucket 設定權限。發布流程會呼叫 `PutBucketLifecycleConfiguration`，替 `instagram-reels/` 設定 3 天後刪除；Cloudflare 將 lifecycle 視為 bucket-level action，若 Token 出現 `AccessDenied`，需改用具有 R2 bucket 設定寫入能力的 Token，或後續將 lifecycle 改成由 Cloudflare Dashboard 手動管理。
5. 建立 Token 後，立即複製並安全保存：
   - **Access Key ID**
   - **Secret Access Key**
6. Secret Access Key 之後無法在 Dashboard 再次查看。遺失時只能撤銷舊 Token、重新建立新的 Token，再回到 Creator Tools 更新。

Cloudflare R2 S3 endpoint 格式如下：

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

本專案會由 Account ID 自動組合 endpoint，UI 不需要額外輸入 endpoint 或 region；程式使用 `region=auto`。若建立的是 EU 或 FedRAMP jurisdiction bucket，請先確認目前程式的 endpoint 組合是否需要對應的 jurisdiction endpoint，不要直接沿用一般 endpoint。

> 最小權限原則：只給本專案使用的 bucket、只建立一組專用 credential，並定期在 Cloudflare Dashboard 檢查與輪替。不要把 Secret Access Key 寫入 Git、README、`.env`、Docker image 或瀏覽器 localStorage。

### 2.4 設定公開 URL：正式環境使用 Custom Domain

Instagram API 必須能從公開網路以 HTTPS 讀取影片。Bucket 預設是 private，因此需要開啟公開存取方式。

#### 建議：連接 Custom Domain

1. 在 Cloudflare **R2** 選擇剛建立的 bucket。
2. 進入 **Settings → Public access → Custom Domains**。
3. 選擇 **Connect Domain／Add**。
4. 輸入一個專用子網域，例如：

   ```text
   r2.example.com
   ```

5. 確認 Cloudflare 要新增的 DNS 記錄，選擇 **Connect Domain**。
6. 等待狀態由 `Initializing` 變成 `Active`。若長時間沒有啟用，重新整理或使用 bucket 旁的重試連線選項。
7. 在 Creator Tools 填入「根網址」，不要加 bucket 名稱、object key、query string 或 fragment：

   ```text
   https://r2.example.com
   ```

Cloudflare 要求 Custom Domain 所屬的網域已加入同一個帳號的 zone。Custom Domain 也能搭配 Cloudflare Cache、WAF 或其他存取控制功能；若日後要限制存取，請確認沒有同時開著會繞過限制的 `r2.dev` 公開入口。

#### 開發測試：使用 `r2.dev`

若尚未準備自己的網域，可在 **Settings → Public Development URL** 選擇 **Enable**，確認輸入 `allow` 後取得 Cloudflare 提供的 URL，例如：

```text
https://pub-xxxxxxxxxxxxxxxx.r2.dev
```

這個 URL 可以先填入 Creator Tools 的 **R2 公開網址／Custom Domain**，但 `r2.dev` 有速率限制，Cloudflare 明確定位為非正式環境用途。不要自行建立 CNAME 指向 `r2.dev`；正式環境請改用 Custom Domain。

### 2.5 設定 CORS（瀏覽器跨來源存取時才需要）

目前 Creator Tools 是由後端上傳到 R2，並由後端以公開 URL 做一次 Range GET 驗證；一般只使用 Instagram 伺服器讀取公開 URL 時，不需要讓瀏覽器直接上傳 R2。若要在前端直接預覽、下載或使用 presigned URL，才需要設定 CORS。

在 bucket 的 **Settings → CORS Policy** 新增規則。開發環境可先使用：

```json
[
  {
    "AllowedOrigins": ["http://localhost:3000"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["Content-Length", "Content-Range", "ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

正式環境請把 `AllowedOrigins` 改成實際前端來源，例如 `https://creator.example.com`，不要為了省事使用 `*`。如果前端也需要直接 PUT 上傳，才另外加入 `PUT`，並只放行實際需要的 request headers。

Cloudflare 的 CORS 回應會依瀏覽器送出的 `Origin` 判斷；使用 `curl` 測試時若沒有加 `Origin` header，可能看不到 `Access-Control-Allow-Origin`。修改已使用 Custom Domain 的 CORS 後，若瀏覽器仍拿到舊回應，請清除該 hostname 的 Cloudflare cache。

### 2.6 設定 Object Lifecycle

本專案的發布程式會在工作開始時建立或更新以下 lifecycle rule：

```text
Rule ID: creator-tools-temporary-reels
Prefix: instagram-reels/
Expiration: 3 days
```

這是後備清理機制，不是主要刪除機制。Reel 成功發布後，程式會立即刪除該支影片；若發布中斷、程序崩潰或刪除失敗，lifecycle 會在期限到達後清除暫存物件。Cloudflare 的 lifecycle 實際刪除通常可能需要最多約 24 小時，不應視為精準的定時刪除。

若要手動在 Cloudflare Dashboard 設定或檢查：

1. 進入 R2 bucket → **Settings → Object Lifecycle Rules**。
2. 選擇 **Add rule**。
3. Rule 名稱填 `creator-tools-temporary-reels`。
4. Prefix 填：

   ```text
   instagram-reels/
   ```

5. 設定物件在建立後 3 天到期，選擇儲存。
6. 確認沒有設定 Bucket Lock 規則阻止刪除；Bucket Lock 的保留期限會優先於 lifecycle。

若發布時看到 lifecycle 的 `AccessDenied`，請不要把錯誤誤判成 Instagram 權限錯誤。這代表 R2 credential 可以（或可能可以）存取物件，但沒有修改 bucket lifecycle 的權限；請依 2.3 的權限說明處理，或調整程式讓 lifecycle 改由部署者手動管理。

### 2.7 填入 Creator Tools

完成 Cloudflare 設定後：

1. 登入 Creator Tools。
2. 開啟 **Instagram → Instagram / R2 設定**。
3. 在 **Cloudflare R2** 區塊填入：

   ```text
   R2 Account ID             = Cloudflare Account ID
   R2 Access Key ID          = R2 API Token 的 Access Key ID
   R2 Secret Access Key      = 建立 Token 當下複製的 Secret Access Key
   R2 Bucket 名稱            = 例如 creator-tools-reels
   R2 公開網址／Custom Domain = 例如 https://r2.example.com
   ```

4. 按 **儲存設定**。
5. 按 **測試 R2**。
6. 測試成功後，再進行一支 Reel 的小量發布驗收。

儲存規則：

- Account ID、Access Key ID、Bucket 名稱和公開網址會保存到 `data/runtime_config.json`。
- Secret Access Key 由後端加密保存於 credential store，不會由設定 API 回傳，也不會放在瀏覽器 Cookie。
- Secret 欄位顯示「已設定；留空保留原值」時，代表不要為了儲存其他欄位而重新填入 Secret。
- `r2_public_base_url` 必須是可公開解析的 HTTPS URL；本專案會拒絕 `http://`、`localhost`、private IP、query string 和 fragment。
- 不要在公開網址後面填 `/instagram-reels`；object key 會由程式自動附加。

### 2.8 驗證流程

#### A. 先驗證公開 URL

在 bucket 中先放一個測試檔案，例如 `instagram-reels/health-check.txt`，再使用無痕視窗開啟：

```text
https://r2.example.com/instagram-reels/health-check.txt
```

必須能在不登入 Cloudflare、不帶 Cookie、不帶 Authorization 的情況下取得檔案。若回傳 `403` 或 `404`，先處理 Custom Domain／Public access／object key，再測試 Creator Tools。

也可以使用 PowerShell：

```powershell
Invoke-WebRequest `
  -Uri "https://r2.example.com/instagram-reels/health-check.txt" `
  -Method Head
```

#### B. 在 Creator Tools 測試 R2 credential

按 **測試 R2** 時，後端會使用 S3 endpoint 對指定 bucket 執行 `HeadBucket`。這一步主要驗證 Account ID、Access Key、Secret 和 Bucket Name；它不代表公開網址一定可以被 Instagram 讀取，因此仍要完成 A。

#### C. 做一支最小發布驗收

1. 選一支可由 Google Drive 下載的短影片。
2. 只選一位 Instagram 測試帳號／人物。
3. 開始發布工作。
4. 確認工作結果依序出現 `uploaded`、`container_created`、`published`。
5. 確認 `R2 暫存影片已刪除`，或在 R2 bucket 中確認對應 `instagram-reels/YYYY/MM/DD/` object 已消失。
6. 若刪除失敗，使用工作頁的重試功能；不要因為 R2 清理失敗就重新建立 Instagram container，避免重複發布。

### 2.9 R2 設定完成檢查表

- [ ] 已建立本專案專用 R2 bucket。
- [ ] 已記下正確的 Cloudflare Account ID。
- [ ] R2 API Token 只授權本專案使用的 bucket。
- [ ] Token 具備物件讀取、寫入與列出權限。
- [ ] 已確認目前 Token 能讓本專案設定 lifecycle；若不能，已依 2.3 調整權限或安排程式改為手動 lifecycle。
- [ ] 已建立正式 Custom Domain，或明確知道目前只是在使用受限制的 `r2.dev` 測試 URL。
- [ ] 公開 URL 使用 HTTPS，且不含 `/instagram-reels`、query string 或 fragment。
- [ ] 在無 Cookie、無 Authorization 的瀏覽器或 HTTP request 中可以讀取測試物件。
- [ ] 若瀏覽器要跨來源存取，已設定正確的 CORS AllowedOrigins。
- [ ] 已設定 `instagram-reels/` prefix 的 3 天 lifecycle。
- [ ] Secret Access Key 沒有寫入 Git、`.env`、Docker image 或前端程式碼。
- [ ] Creator Tools 的 **測試 R2** 成功。
- [ ] 已完成一支 Reel 的小量端到端驗收。

### 2.10 本專案的 R2 生命週期與資料流

```text
Google Drive
    ↓ 後端下載
Cloudflare R2: instagram-reels/YYYY/MM/DD/...
    ↓ 公開 HTTPS URL + Range GET 驗證
Instagram Graph API 讀取影片並建立 Reel
    ↓ 發布成功
Creator Tools 立即刪除 R2 object
    ↓ 若中斷或刪除失敗
R2 lifecycle 在 3 天後清理 instagram-reels/ 暫存物件
```

Reel 成功發布後，工作流程會立即刪除該支影片的 R2 object；lifecycle 仍作為清理失敗或中斷工作的後備保護。若刪除暫時失敗，工作會保留 `published` 狀態並提供重試清理，不會重複發布 Instagram 影片。

## 3. Reels 工作流程

Drive list 使用 pagination 與 `videoMediaMetadata` 做可取得欄位的 preflight；影片下載後再用 `ffprobe` 讀取實際媒體資訊。發布工作透過：

```text
POST /api/v1/instagram/publish-jobs
GET  /api/v1/instagram/publish-jobs/{id}
POST /api/v1/instagram/publish-jobs/{id}/retry
```

每片會保存 `queued`、`uploaded`、`container_created`、`published`、`failed`、`paused` 與 creation/media ID。第一片失敗會暫停後續；retry 會沿用已保存的 creation ID。結果保存於 `data/instagram_publish_jobs.json`。

Reels preflight 只採用 Meta 官方列出的限制：MOV/MP4、AAC 48 kHz、H.264/HEVC、23–60 FPS、水平寬度最多 1920 pixels、影片 bitrate 最多 25 Mbps、音訊 bitrate 128 kbps、3 秒至 15 分鐘、檔案最多 1 GB。9:16 是 Meta 的建議比例，不會被本專案當成硬限制；若 Drive 缺少 metadata，會保留影片並在下載後檢查，最終仍以 Meta API 的實際驗證結果為準。規格來源：[Meta 官方 Instagram API Reels Publishing collection](https://www.postman.com/meta/instagram/folder/23987686-8cdc2637-eebc-4770-aa59-7b0a0bba5a64)。

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

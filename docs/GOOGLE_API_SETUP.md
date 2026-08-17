# Google API 與 OAuth 2.0 設定

Creator Tools 使用兩個獨立的 OAuth 流程：控制台登入／Google Sheets，以及 YouTube 頻道授權。Google 登入可與 YouTube primary 使用同一組 OAuth client；secondary 若啟用則需另一組 client。

## Google Cloud 設定

1. 建立 Google Cloud project。
2. 啟用 Google Sheets API、Google Drive API 與 YouTube Data API v3。
3. 建立 Web application OAuth client。
4. OAuth consent screen 至少加入測試帳號，並讓使用者同意實際需要的 scope。控制台流程使用 OpenID email/profile、`spreadsheets.readonly` 與 `drive.readonly`；YouTube 流程使用 YouTube 管理所需的 `youtube` scope。
5. 將下列 callback URI 加入 Authorized redirect URIs：

```text
http://localhost:8000/api/v1/auth/callback
https://your-domain.example/api/v1/auth/callback
```

正式 callback 必須是 `PUBLIC_BASE_URL` 加上 `/api/v1/auth/callback`。`BIND_HOST`、`PORT` 與 `HOST_PORT` 不會被用來猜測公開網址；若反向代理使用非標準 port，公開 URL 必須保留該 port。

## 後端環境變數

從根目錄 `.env.example` 建立 `.env`。空白的 `ALLOWED_GOOGLE_EMAILS` 只適合本機 HTTP 開發；正式環境或 HTTPS 必須填入實際允許登入的 Google 帳號，不能直接保留範例值。

```env
ENVIRONMENT=development
BIND_HOST=0.0.0.0
PORT=8000
HOST_PORT=8000
PUBLIC_BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
TRUSTED_HOSTS=
SECRET_KEY=
CREDENTIAL_ENCRYPTION_KEY=
ALLOWED_GOOGLE_EMAILS=

GOOGLE_CLIENT_ID=your-login-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-login-client-secret

YOUTUBE_OAUTH_PRIMARY_CLIENT_ID=your-primary-client-id.apps.googleusercontent.com
YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET=your-primary-client-secret
YOUTUBE_OAUTH_PRIMARY_LABEL=Primary
YOUTUBE_OAUTH_SECONDARY_ENABLED=false
YOUTUBE_OAUTH_SECONDARY_CLIENT_ID=
YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET=
YOUTUBE_OAUTH_SECONDARY_LABEL=Secondary
YOUTUBE_OAUTH_DEFAULT_SLOT=primary

YOUTUBE_PRIMARY_GENERAL_QUOTA_LIMIT=10000
YOUTUBE_PRIMARY_QUOTA_SAFETY_BUFFER_UNITS=1000
YOUTUBE_SECONDARY_GENERAL_QUOTA_LIMIT=10000
YOUTUBE_SECONDARY_QUOTA_SAFETY_BUFFER_UNITS=1000
YOUTUBE_PRIMARY_VIDEO_UPLOADS_QUOTA_LIMIT=100
YOUTUBE_SECONDARY_VIDEO_UPLOADS_QUOTA_LIMIT=100
```

`GOOGLE_CLIENT_ID`／`GOOGLE_CLIENT_SECRET` 只供控制台登入；YouTube OAuth slot 的 client 設定獨立保存。primary 可以填相同值，但兩組環境變數仍需同時存在。client secret、`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY` 與 token 只放在後端環境或 `data/` 的受保護資料中，不會傳給前端。

## 啟動與檢查

```powershell
copy .env.example .env
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

確認 `http://localhost:8000/api/v1/health` 回傳 `status: "healthy"`，並檢查 `ready`、`configuration`、`youtube` 與 `warnings`。health response 只回報設定狀態，不回傳 client secret。

登入成功後，控制台 Google Sheet 在「帳號與 Google 設定」保存；YouTube playlist、slot 與配額設定在「YouTube 設定」保存。這些帳號工作狀態會寫入 `data/account_state.json` 與 runtime 設定檔，不必放入 `.env`。

## Google Drive 上傳

「上傳至 YouTube」接受 Drive 資料夾或單一影片的 ID／網址。資料夾只讀取第一層，影片會依檔名自然排序，逐部下載到受保護的暫存區，再以 YouTube resumable upload 上傳為 `private`，最後加入帳號共用的 To-Post 播放清單。

Drive 登入 scope 是 `https://www.googleapis.com/auth/drive.readonly`。既有登入 token 沒有這個 scope 時，頁面會要求重新授權；此 scope 屬於 Google Drive restricted scope，正式公開部署可能需要完成 Google OAuth 驗證與安全評估。系統只接受 `drive.google.com` 的來源輸入，不會直接請求使用者貼上的任意 URL。

上傳工作與暫存資料保存於 `data/`；Docker 部署必須保留既有的 `./data:/app/data` volume。後端工作 API 為：

- `POST /api/v1/youtube/uploads/preview`
- `POST /api/v1/youtube/uploads/jobs`（回傳 `202` 與 `job_id`）
- `GET /api/v1/youtube/uploads/jobs/{job_id}`
- `POST /api/v1/youtube/uploads/jobs/{job_id}/cancel`
- `POST /api/v1/youtube/uploads/jobs/{job_id}/retry`

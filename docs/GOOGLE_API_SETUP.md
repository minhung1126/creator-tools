# Google API 申請與 OAuth 2.0 設定教學

Creator Tools 需要 Google Sheets 與 YouTube Data API v3 的 OAuth 2.0 授權。

## 1. Google Cloud 設定

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 建立登入/Sheets 用的 `Creator-Tools` 專案，並啟用 Google Sheets API。
2. 建立一個或兩個 YouTube Data API v3 專案／Web Client，分別填入 primary 與 optional secondary slot。兩個 client 可共用 callback，但 quota ledger 與授權 token 在 Creator Tools 中分開保存。
3. 在 OAuth consent screen 加入 userinfo email/profile、Sheets readonly 與 YouTube scopes；本專案不需要 Google Drive scope。
4. Development Mode 請把測試管理者加入 Test users。
5. 建立 Web application OAuth client，設定 callback：

```text
http://localhost:8000/api/v1/auth/callback
https://your-domain.com/api/v1/auth/callback
```

正式 callback 必須是 `PUBLIC_BASE_URL` 加上 `/api/v1/auth/callback`；若 reverse proxy 對外是 `8443`，公開 URL 就保留 `https://your-domain.com:8443/...`。`BIND_HOST` 與 `PORT` 不會被拿來猜 public URL。

## 2. 後端 `.env`

```env
BIND_HOST=0.0.0.0
PORT=8000
PUBLIC_BASE_URL=https://your-domain.com
FRONTEND_URL=https://your-domain.com
SECRET_KEY=generate-a-unique-secret
CREDENTIAL_ENCRYPTION_KEY=generate-a-stable-encryption-key
ALLOWED_GOOGLE_EMAILS=admin@example.com
GOOGLE_CLIENT_ID=your-login-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-login-client-secret
YOUTUBE_OAUTH_PRIMARY_CLIENT_ID=your-youtube-primary-client-id.apps.googleusercontent.com
YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET=your-youtube-primary-client-secret
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
```

正式環境未設定 `ALLOWED_GOOGLE_EMAILS` 時會拒絕登入。Google client secret 只放後端 `.env`，不得傳給前端。

登入後的預設 Google Sheet 與 YouTube 播放清單不放在 `.env`；請到「全域與 Google 設定」設定共用 Sheet，並到 YouTube 分組中的「YouTube 設定」設定播放清單。這些值會保存於伺服器的 `data/runtime_config.json`。

## 3. 驗證

登入後，系統會把 Google token 加密存於 server-side credential store；瀏覽器 cookie 只有 opaque session ID。YouTube token 會保存為 `youtube_primary`／`youtube_secondary`，client secret 永不持久化。OAuth callback 會用簽名 cookie 中的 slot 驗證流程，不能以 callback URL 參數改寫 slot。修改 `.env` 後請重新啟動服務。

Primary 會暫時 fallback 到既有 `GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET`，Health Check 會顯示 migration warning。OAuth slot 的兩個授權若回傳不同 Channel ID，第二個 slot 不會被啟用；控制台也只會在有效授權與頻道驗證完成後允許設為 active。

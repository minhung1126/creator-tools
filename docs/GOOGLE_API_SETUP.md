# Google API 申請與 OAuth 2.0 設定教學

Creator Tools 需要 Google Sheets、YouTube Data API v3 與 Google Drive API 的 OAuth 2.0 授權。

## 1. Google Cloud 設定

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 建立 `Creator-Tools` 專案。
2. 啟用 Google Sheets API、YouTube Data API v3 與 Google Drive API。
3. 在 OAuth consent screen 加入必要 scopes：userinfo email/profile、Sheets readonly、YouTube、Drive readonly。
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
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

正式環境未設定 `ALLOWED_GOOGLE_EMAILS` 時會拒絕登入。Google client secret 只放後端 `.env`，不得傳給前端。

登入後的預設 Google Sheet 與 YouTube 播放清單不放在 `.env`；請到網頁的「Google / YouTube 設定」頁輸入並儲存。這些值會保存於伺服器的 `data/runtime_config.json`。

## 3. 驗證

登入後，系統會把 Google token 加密存於 server-side session store；瀏覽器 cookie 只有 opaque session ID。登出只會刪除目前 session。修改 `.env` 後請重新啟動服務。

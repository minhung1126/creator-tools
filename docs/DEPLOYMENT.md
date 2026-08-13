# Docker & Production 部署指南

Creator Tools 的 production image 可由 GitHub Actions 發布至 GHCR；本機 Compose 預設從已鎖定 digest 的 Dockerfile build，掛載 `data/` 並啟動服務。

## 1. 準備環境

1. 安裝 Docker Engine/Docker Compose v2。
2. 建立 `.env`，參考根目錄 `.env.example`。
3. 正式環境至少設定 `ENVIRONMENT=production`、`BIND_HOST`、`PUBLIC_BASE_URL`、`FRONTEND_URL`、`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY`、`ALLOWED_GOOGLE_EMAILS`、登入 Google OAuth 憑證與 YouTube primary OAuth 憑證。Google OAuth 與 YouTube primary slot 可以填相同的 client ID／client secret；secondary 是 optional，但啟用時 client ID/secret 必須成對存在。

`PUBLIC_BASE_URL` 是 Google callback 的唯一來源；`BIND_HOST` 只控制容器內 bind address。若 reverse proxy 位於 homelab 的另一台設備，Creator Tools 主機必須讓該設備可以連到 `8000`，建議設定成：

```env
ENVIRONMENT=production
BIND_HOST=0.0.0.0
PORT=8000
HOST_PORT=8000
PUBLIC_BASE_URL=https://creator-tools.ymin.io
FRONTEND_URL=https://creator-tools.ymin.io
TRUSTED_HOSTS=creator-tools.ymin.io
SECRET_KEY=請改成唯一且隨機的長字串
CREDENTIAL_ENCRYPTION_KEY=請固定保存的加密金鑰
ALLOWED_GOOGLE_EMAILS=admin@example.com
GOOGLE_CLIENT_ID=你的登入 Google OAuth Client ID
GOOGLE_CLIENT_SECRET=你的登入 Google OAuth Client Secret
YOUTUBE_OAUTH_PRIMARY_CLIENT_ID=可與上方 GOOGLE_CLIENT_ID 相同
YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET=可與上方 GOOGLE_CLIENT_SECRET 相同
YOUTUBE_OAUTH_SECONDARY_ENABLED=false
YOUTUBE_OAUTH_SECONDARY_CLIENT_ID=
YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET=
YOUTUBE_OAUTH_DEFAULT_SLOT=primary
```

此 production image 已包含編譯後的前端，前端與 API 可以共用同一個公開網址：`/` 由前端提供，`/api/*` 由 API 處理。Compose 預設只將 container port 綁到本機 loopback；reverse proxy 應與 Creator Tools 在同一台主機。若 proxy 位於另一台設備，請將 `docker-compose.yml` 的 bind address 改成明確的私有 LAN IP，並以防火牆只允許該 proxy 存取，勿綁定到公開介面。

## 2. 啟動與更新

```powershell
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs -f creator-tools
```

更新同樣先 `build --pull` 再 `up -d`。GitHub Actions 會同時發布不可變的 commit SHA tag，以及預設分支的 `latest` tag。使用 GHCR 時可拉取 `latest` 取得主線最新版本；正式回滾或需要可重現部署時，請改用完整 commit SHA tag。

## 3. 持久化與驗證

- `./data:/app/data` 保存加密 credential store、server-side sessions、帳號工作狀態、runtime config，以及 JSON-backed YouTube quota 用量。
- 目前需持久保存的主要檔案包括：

  ```text
  data/credential_store.json
  data/sessions.json
  data/account_state.json
  data/runtime_config.json
  data/youtube_quota_usage.json
  data/youtube_quota_usage.secondary.json
  ```

  實務上建議直接備份整個 `data/` volume，而不是只挑單一檔案。YouTube metadata 與發布清理會在 API request 內直接執行，不再建立背景任務、通知或歷史資料。
- 不要把 `.env`、`data/credential_store.json`、`data/sessions.json` 或 `data/account_state.json` 提交到 Git。
- Health check：`https://creator-tools.ymin.io/api/v1/health`。除了 HTTP 200，也要確認 JSON 的 `ready: true`；`configuration` 與 `warnings` 只揭露設定是否齊全，不會回傳任何金鑰。
- Google Authorized Redirect URI：`https://creator-tools.ymin.io/api/v1/auth/callback`。
部署完成後，Google 登入並確認設定頁顯示的 `redirect_uri` 與上方網址逐字一致；若 `.env` 有修改，必須重新啟動 container。

正式環境未設定 `ALLOWED_GOOGLE_EMAILS` 時，Google login 會被拒絕；目前產品模式是單一管理者。

登入後的 Google Sheet、YouTube playlist、Video/Shorts 草稿、Sheet 顯示選項、發布清單輸入與導覽狀態，會依 Google 帳號保存到 `data/account_state.json`，不需要放進 `.env`。修改網頁設定後不必重啟服務；修改 `.env` 則需要重新啟動。

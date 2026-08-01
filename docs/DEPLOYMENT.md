# Docker & Production 部署指南

Creator Tools 的 production image 已由 GitHub Actions 建置並發布至 GHCR；Compose 只負責拉取 image、掛載 `data/` 與啟動服務。

## 1. 準備環境

1. 安裝 Docker Engine/Docker Compose v2。
2. 建立 `.env`，參考根目錄 `.env.example`。
3. 正式環境至少設定 `BIND_HOST`、`PUBLIC_BASE_URL`、`FRONTEND_URL`、`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY`、`ALLOWED_GOOGLE_EMAILS` 與 Google OAuth 憑證。

`PUBLIC_BASE_URL` 是 Google/Instagram callback 的唯一來源；`BIND_HOST` 只控制容器內 bind address。若 reverse proxy 位於 homelab 的另一台設備，Creator Tools 主機必須讓該設備可以連到 `8000`，建議設定成：

```env
BIND_HOST=0.0.0.0
PORT=8000
PUBLIC_BASE_URL=https://creator-tools.ymin.io
FRONTEND_URL=https://creator-tools.ymin.io
```

此 production image 已包含編譯後的前端，前端與 API 可以共用同一個公開網址：`/` 由前端提供，`/api/*` 由 API 處理。Homelab reverse proxy 應將公開網址轉發到 Creator Tools 主機的 `8000` port。

## 2. 啟動與更新

```powershell
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f creator-tools
```

更新同樣先 `pull` 再 `up -d`。Compose 使用 `image` 而非 `build`；不要在 production 流程使用 `docker compose up --build`。

## 3. 持久化與驗證

- `./data:/app/data` 保存加密 credential store、server-side sessions、runtime config 與 Instagram publish jobs。
- 不要把 `.env`、`data/credential_store.json` 或 `data/sessions.json` 提交到 Git。
- Health check：`https://creator-tools.ymin.io/api/v1/health`。
- Google Authorized Redirect URI：`https://creator-tools.ymin.io/api/v1/auth/callback`。
- Meta Valid OAuth Redirect URI：`https://creator-tools.ymin.io/api/v1/instagram/auth/callback`。

正式環境未設定 `ALLOWED_GOOGLE_EMAILS` 時，Google login 會被拒絕；目前產品模式是單一管理者。

登入後的 Google Sheet、YouTube playlist、Drive folder 與 R2 設定都由網頁設定頁保存到 `data/`，不需要放進 `.env`。修改網頁設定後不必重啟服務；修改 `.env` 則需要重新啟動。

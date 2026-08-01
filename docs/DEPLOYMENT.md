# Docker & Production 部署指南

Creator Tools 的 production image 已由 GitHub Actions 建置並發布至 GHCR；Compose 只負責拉取 image、掛載 `data/` 與啟動服務。

## 1. 準備環境

1. 安裝 Docker Engine/Docker Compose v2。
2. 建立 `.env`，參考根目錄 `.env.example`。
3. 正式環境至少設定 `BIND_HOST`、`PUBLIC_BASE_URL`、`FRONTEND_URL`、`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY`、`ALLOWED_GOOGLE_EMAILS` 與 Google OAuth 憑證。

`PUBLIC_BASE_URL` 是 Google/Instagram callback 的唯一來源，例如 `https://creator.example.com:8443`；`BIND_HOST` 只控制容器內 bind address。

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
- Health check：`https://creator.example.com/api/v1/health`。
- Google Authorized Redirect URI：`PUBLIC_BASE_URL/api/v1/auth/callback`。
- Meta Valid OAuth Redirect URI：`PUBLIC_BASE_URL/api/v1/instagram/auth/callback`。

正式環境未設定 `ALLOWED_GOOGLE_EMAILS` 時，Google login 會被拒絕；目前產品模式是單一管理者。

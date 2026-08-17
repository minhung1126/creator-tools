# Docker 與 production 部署

`Dockerfile` 會先在 Node 20 Alpine 階段執行 `npm ci` 與 `npm run build`，再把 `frontend/dist` 複製到 Python 3.11 image。執行中的 FastAPI 應用程式是 `backend.app.main:app`，容器對外提供 port 8000。

## 準備環境

1. 安裝 Docker Engine 與 Docker Compose v2。
2. 在專案根目錄建立 `.env`：

```powershell
copy .env.example .env
```

3. 至少設定下列正式環境值：

```env
ENVIRONMENT=production
BIND_HOST=0.0.0.0
PORT=8000
HOST_PORT=8000
PUBLIC_BASE_URL=https://your-domain.example
FRONTEND_URL=https://your-domain.example
TRUSTED_HOSTS=your-domain.example
SECRET_KEY=請替換成至少32字元且持久保存的隨機值
CREDENTIAL_ENCRYPTION_KEY=請替換成不同且持久保存的加密金鑰
ALLOWED_GOOGLE_EMAILS=請替換成實際允許登入的 Google 帳號
GOOGLE_CLIENT_ID=請填入控制台登入 OAuth client ID
GOOGLE_CLIENT_SECRET=請填入控制台登入 OAuth client secret
YOUTUBE_OAUTH_PRIMARY_CLIENT_ID=請填入 YouTube primary OAuth client ID
YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET=請填入 YouTube primary OAuth client secret
YOUTUBE_OAUTH_SECONDARY_ENABLED=false
YOUTUBE_OAUTH_SECONDARY_CLIENT_ID=
YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET=
YOUTUBE_OAUTH_DEFAULT_SLOT=primary
```

上方含有「請替換」的值不能直接拿來啟動正式服務；請用實際值取代。若啟用 secondary，client ID 與 client secret 必須成對存在。

`PUBLIC_BASE_URL` 是 OAuth callback 與 health response 的公開來源。Google Authorized redirect URI 必須逐字設定為：

```text
https://your-domain.example/api/v1/auth/callback
```

`BIND_HOST`、`PORT` 控制應用程式在容器內的監聽位址；Compose 的 `HOST_PORT` 控制主機端 port。Compose 預設只將主機 `127.0.0.1:${HOST_PORT}` 映射到容器 8000，反向代理若位於另一台主機，請將 bind address 改為明確的私有 LAN 位址並以防火牆限制來源。

## 建置與啟動

```powershell
docker compose config
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs -f creator-tools
```

`docker compose config` 需要先存在 `.env`，也可用來確認 interpolation 與 volume 路徑。Compose 使用 `./data:/app/data` 保存執行期資料。

## 前端快取與版本驗證

FastAPI 會對首頁及其他 HTML 回傳：

```text
Cache-Control: no-cache, max-age=0, must-revalidate
```

Vite 產生的 `/assets/*-<hash>.js` 與 `/assets/*-<hash>.css` 則回傳一年 immutable 快取。若前方使用 Cloudflare 或其他 CDN，請確認 Browser Cache TTL 沒有覆寫 origin 的 HTML header，也不要對首頁套用一年 immutable 規則；不需要使用 `Clear-Site-Data`。

部署後至少確認：

```powershell
$base = "https://your-domain.example"
(Invoke-WebRequest "$base/" -UseBasicParsing).Headers['Cache-Control']
$html = (Invoke-WebRequest "$base/" -UseBasicParsing).Content
$assets = [regex]::Matches($html, '/assets/[^"'']+\.(?:js|css)') | ForEach-Object Value | Sort-Object -Unique
foreach ($asset in $assets) {
  $response = Invoke-WebRequest "$base$asset" -UseBasicParsing
  "$asset :: $($response.StatusCode) :: $($response.Headers['Content-Type']) :: $($response.Headers['Cache-Control'])"
}
```

`APP_COMMIT_SHA` 會同時傳給 backend runtime 與 frontend builder 的 `VITE_APP_COMMIT_SHA`；health API 的 `commit_sha` 可用來辨識前後端版本是否一致。部署策略應盡量保留至少前一版 hashed assets；若暫時無法保留，首頁的 no-cache/revalidation 規則不可被 CDN 覆寫。

## 健康檢查與資料保存

- Health endpoint：`/api/v1/health`。Compose healthcheck 會以 `curl` 檢查 HTTP 200；部署後仍需確認 JSON 的 `ready` 為 `true`。
- OAuth callback：`/api/v1/auth/callback`。
- `data/` 包含加密憑證、session、帳號工作狀態、runtime 設定與兩個 YouTube 配額 ledger。服務重建或搬遷時必須保留整個 volume。
- 不要提交 `.env`、`data/` 或任何 client secret。修改 `.env` 後要重新建立或重啟容器。
- 正式環境若遇到 `409 stale_preview`，請讓使用者重新讀取並確認完整預覽；不要在 proxy 或 client 層自動重送寫入請求。
- API 錯誤的公開格式固定為 `detail.code`、`detail.message`、`detail.retryable`、`detail.field_errors`；不要把 provider 原始錯誤 body 寫入 response 或 log。

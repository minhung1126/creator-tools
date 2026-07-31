# Docker & Production 部署指南 (Deployment Guide)

本系統提供 Docker 與 Docker Compose 配置，支援在 Linux / macOS / Windows 雲端伺服器（如 AWS, GCP, DigitalOcean, Synology）一鍵部署。

---

## 1. 部署前準備 (Prerequisites)

1. 安裝 Docker 與 Docker Compose (建議 Docker Desktop 或 Docker Engine v24+)。
2. 確保伺服器 Port `8000` 未被佔用（或於 `docker-compose.yml` 修改 Port 映射）。
3. 準備好 `.env` 設定檔（可參考根目錄 `.env.example`）。

---

## 2. 環境變數設定 (`.env`)

請在專案根目錄建立 `.env` 檔案，填入以下必要設定：

```env
# 1. 伺服器主機名稱與通訊埠
HOST=localhost
PORT=8000

# 2. Google OAuth 2.0 Client 金鑰 (必須於後端 .env 集中管理)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret

# 3. Session 加密 Secret Key
SECRET_KEY=generate-a-secure-random-key-here

# 4. 預設資源 IDs (選填，亦可於 Web UI「系統設定」頁面配置並持久化至 runtime_config.json)
DEFAULT_SPREADSHEET_ID=1xsxDJ80-TOQs3d3ecHALEbyMlxxEkwXNjHaW7yA8wVs
DEFAULT_PLAYLIST_ID=PLhu1MP3FpZmHar5qPZJkl6zCqXzddF4nC
```

> ⚠️ **重點注意事項：**
> - **HOST 與 PORT 分離**：`HOST` 僅需指定主機名稱（例如 `localhost` 或 `your-domain.com`），無須前綴 `http://`。當 `HOST` 為 `localhost` 或 `127.0.0.1` 時，系統會自動選用 `http://` 協定；於正式域名環境則自動使用 `https://` 協定並啟用安全 Cookie。
> - **OAuth 重導向網址 (Authorized Redirect URIs)**：請將 `http://<HOST>:<PORT>/api/v1/auth/callback`（例如 `http://localhost:8000/api/v1/auth/callback` 或 `https://your-domain.com:8000/api/v1/auth/callback`）填入 Google Cloud Console 的 **「已授權的重導向 URI」** 設定中。
> - **Credentials 管理**：Google Client ID 與 Client Secret 屬於敏感憑證，**嚴禁** 由前端 UI 編輯或傳輸，必須由後端 `.env` 檔案管理。

---

## 3. 使用 Docker Compose 一鍵啟動 (Recommended)

在專案根目錄執行以下指令：

```bash
# 1. 建置與啟動容器
docker compose up -d --build

# 2. 查看容器執行狀態
docker compose ps

# 3. 檢視即時 Log 日誌
docker compose logs -f
```

啟動後，使用瀏覽器開啟 `http://your-domain.com:8000` 即可進入 Creator Tools Web 控制台。

---

## 4. 停止與更新服務 (Stop & Update)

```bash
# 停止服務
docker compose down

# 更新代碼後重新建置並啟動
docker compose up -d --build
```

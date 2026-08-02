# 🎬 Creator Tools Web Dashboard

一個整合 YouTube 草稿管理、metadata 更新與發布清理的創作者自動化 Web 控制台。後端使用 Python FastAPI，前端使用 React，並透過 Google OAuth 2.0 存取 Google Sheets 與 YouTube。

![System Overview](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green) ![React](https://img.shields.io/badge/React-18.2-cyan) ![Docker](https://img.shields.io/badge/Docker-Ready-blue)

---

## 🌟 核心功能亮點

1. **🔑 Google OAuth 2.0 與平台分頁設定**
   - 整合 Google Sheets readonly 與 YouTube Data API v3 權限。
   - Google 與 YouTube 使用各自的設定頁。
   - 工作流程設定會持久化儲存；敏感 token / secret 不會由設定 API 回傳前端。

2. **📝 YouTube Video / Shorts 草稿管理**
   - Video 與 Shorts 使用獨立頁面，各自記住工作表、欄位、團體與人物篩選。
   - 人物與全隊選項依 Google Sheet 原始列順序顯示。
   - 支援逐片選人、批量勾選套用、隨機人物欄位抽查與縮圖放大預覽。
   - 安全保留 YouTube 既有 categoryId、tags 等 metadata。

3. **🚀 YouTube 草稿發布與播放清單清理**
   - 讀取待發布 To-Post 播放清單，依上傳時間由早到晚處理。
   - 將影片切換為 `public` 後，自動自播放清單移除，不刪除頻道影片。
   - YouTube 操作在 API request 內依序執行，完成後直接回傳每支影片結果，不依賴背景任務隊列。
   - 顯示本應用程式估算的 YouTube Data API quota 使用量。

4. **♻️ OAuth Token 自動管理**
   - Google Access Token 到期前 5 分鐘自動刷新，最新 token 與 refresh token 加密保存於 `data/credential_store.json`。
   - Refresh 失敗會記錄狀態並提示重新授權；瀏覽器 Cookie 只保存隨機 session id，不保存 OAuth token。

5. **📊 JSON-backed YouTube quota 保護**
   - 每次 request 依官方 method cost 先保留估算額度，並以安全 buffer 避免超額。
   - 用量與 quota breaker 狀態保存於 `data/youtube_quota_usage.json`，不需要 SQLite 任務資料庫。
   - Google 回報 `quotaExceeded` 後會停止新 request，直到 Pacific Time 午夜重設。

---

## 📁 專案架構目錄

```text
creator-tools/
├── backend/
│   ├── app/
│   │   ├── api/              # auth, settings, sheets, youtube
│   │   ├── core/             # 環境變數、安全 Session、設定
│   │   ├── services/         # Google、Sheets、YouTube
│   │   └── main.py
│   ├── requirements.txt
│   └── tests/              # mock-only pytest tests
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── App.jsx
│   ├── index.html
│   └── vite.config.js
├── docs/
│   ├── DEPLOYMENT.md
│   ├── GOOGLE_API_SETUP.md
│   └── YOUTUBE_QUOTA.md
├── .env.example
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🚀 本地開發快速啟動

### 1. 後端

確保已安裝 Python 3.11+，在專案根目錄執行：

```bash
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

pip install -r backend/requirements.txt
copy .env.example .env
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

後端 Health Check：`http://localhost:8000/api/v1/health`。啟動後先確認回應中的 `ready` 是 `true`；若為 `false`，`warnings` 會直接列出尚缺的登入設定。即使程序存活，只要 OAuth 尚未備妥就不會誤報為可登入。

### 2. 前端

另開終端機：

```bash
cd frontend
npm install
npm run dev
```

瀏覽器開啟 `http://localhost:3000`。

---

## 📖 設定與部署文件

- [Google API 申請與 OAuth 2.0 設定教學](docs/GOOGLE_API_SETUP.md)
- [YouTube Data API quota 說明](docs/YOUTUBE_QUOTA.md)
- [Docker 部署說明](docs/DEPLOYMENT.md)

### OAuth Token 維運注意事項

- 正式環境必須固定 `CREDENTIAL_ENCRYPTION_KEY`；金鑰變更後既有加密 token 無法解密，需要重新授權。
- Docker／服務重建時必須保留 `./data` volume，否則會遺失加密 token、session、工作流程設定與 YouTube quota 估算。
- Google 登入 session 仍有安全期限；session 失效代表需要重新登入，不代表 Google refresh token 已失效。

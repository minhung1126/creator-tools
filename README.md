# 🎬 YouTube Creator Tools Web Dashboard

一個為 YouTube 創作者打造的整合式自動化 Web 控制台系統。原為 n8n 自動化工作流，現已完整重構成具備質感暗色 UI、高擴充性 Python (FastAPI) 後端、以及完整 Google OAuth 2.0 授權管理的網頁應用程式。

![System Overview](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green) ![React](https://img.shields.io/badge/React-18.2-cyan) ![Docker](https://img.shields.io/badge/Docker-Ready-blue)

---

## 🌟 核心功能亮點 (Key Features)

1. **🔑 Google OAuth 2.0 統一授權與資源管理中心**
   - 整合管理 Google Sheets, YouTube Data API v3, 與 Google Drive 之 OAuth 2.0 連線。
   - 支援線上與 `.env` 檔案載入 `HOST` 伺服器網址、Google Client ID / Client Secret、預設 Google Sheet 網址/ID 以及預設 YouTube 播放清單 ID。
   - **高擴充性架構**：預留 Meta API (Facebook / Instagram) 設定介面與後端模組。

2. **📝 YouTube 草稿影片資訊批次更新 (Batch Metadata Updater)**
   - 自動讀取對照 Sheet (`Youtube Video` 與 `Youtube Shorts` 工作表)，動態解析選單與團體/人物資料。
   - **頂端篩選列 (Top Control Filter Bar)**：頁面最上方即時切換 `Video` / `Shorts` 類型、篩選所屬團體、以及關鍵字過濾選單人物。
   - 卡片式預覽草稿影片縮圖、標題、Video ID、發布日期，一頁為每支影片指定套用人物並批次更新 YouTube metadata (安全保留 categoryId, tags 等原資料)。

3. **🚀 YouTube 草稿發布與播放清單清理 (Publish & Playlist Cleanup)**
   - 讀取待發布 (To-Post) 播放清單，依發布時間由舊到新排序。
   - 二次確認總覽，逐支將影片公開狀態切換為 `public`，成功後自動呼叫 `playlistItems.delete` 移出播放清單（不刪除 YouTube 頻道原始影片）。

---

## 📁 專案架構目錄 (Directory Structure)

```
creator-tools/
├── backend/                  # Python FastAPI 後端服務
│   ├── app/
│   │   ├── api/              # API 路由 (auth, settings, sheets, youtube)
│   │   ├── core/             # 環境變數與安全 Session 設定
│   │   ├── services/         # Google OAuth, Sheets, YouTube 邏輯封裝
│   │   └── main.py           # FastAPI 應用程式主入口
│   └── requirements.txt
├── frontend/                 # Vite + React 前端控制台
│   ├── src/
│   │   ├── components/       # 導覽列與共用 UI 組件
│   │   ├── pages/            # 儀表板、批次更新、發布清理、系統設定頁面
│   │   ├── services/         # API Client 通訊庫
│   │   └── App.jsx
│   ├── index.html
│   └── vite.config.js
├── docs/                     # 模組化說明文件
│   ├── DEPLOYMENT.md         # Docker & Docker Compose 部署教學
│   └── GOOGLE_API_SETUP.md   # Google Cloud API 申請與 OAuth 設定指南
├── .env.example              # 環境變數設定檔範本
├── Dockerfile                # 多階段容器化打包 Dockerfile
├── docker-compose.yml        # Docker Compose 快速啟動配置
└── README.md
```

---

## 🚀 本地開發快速啟動 (Local Quick Start)

### 1. 後端 (Python FastAPI) 啟動
確保已安裝 Python 3.11+。在專案根目錄開啟終端機：

```bash
# 建立並啟用虛擬環境
python -m venv venv

# Windows PowerShell 啟用：
.\venv\Scripts\Activate.ps1

# 安裝後端依賴
pip install -r backend/requirements.txt

# 複製環境變數範本並填入設定
copy .env.example .env

# 啟動 FastAPI 後端伺服器 (埠號 8000)
uvicorn backend.app.main:app --reload --port 8000
```
後端 Health Check URL: `http://localhost:8000/api/v1/health`

### 2. 前端 (Vite + React) 啟動
另開一個終端機視窗，進入 `frontend` 目錄：

```bash
cd frontend

# 安裝前端套件
npm install

# 啟動 Vite 開發伺服器 (埠號 3000)
npm run dev
```
瀏覽器開啟 `http://localhost:3000` 即可進入系統。

---

## 🐳 正式環境 Docker 部署

如需使用 Docker 或 Docker Compose 進行線上部署，請參閱詳細說明文件：
📖 **[Docker 部署說明文件 (docs/DEPLOYMENT.md)](file:///d:/code/creator-tools/docs/DEPLOYMENT.md)**

---

## 🔑 Google API 與 Credentials 申請

如何建立 Google Cloud 專案、啟用 Sheets/YouTube/Drive API，以及設定 Authorized Redirect URI 的完整圖文步驟教學：
📖 **[Google API 申請與 OAuth 設定教學 (docs/GOOGLE_API_SETUP.md)](file:///d:/code/creator-tools/docs/GOOGLE_API_SETUP.md)**

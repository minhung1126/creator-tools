# 🎬 Creator Tools Web Dashboard

一個整合 YouTube 草稿管理與 Instagram Reels 自動發布的創作者自動化 Web 控制台。後端使用 Python FastAPI，前端使用 React，並透過 Google OAuth 2.0 存取 Google Sheets、Google Drive 與 YouTube。

![System Overview](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green) ![React](https://img.shields.io/badge/React-18.2-cyan) ![Docker](https://img.shields.io/badge/Docker-Ready-blue)

---

## 🌟 核心功能亮點

1. **🔑 Google OAuth 2.0 與平台分頁設定**
   - 整合 Google Sheets、YouTube Data API v3 與 Google Drive readonly 權限。
   - Google、YouTube、Instagram / R2 各自使用獨立設定頁。
   - 工作流程設定會持久化儲存；敏感 token / secret 不會由設定 API 回傳前端。

2. **📝 YouTube Video / Shorts 草稿管理**
   - Video 與 Shorts 使用獨立頁面，各自記住工作表、欄位、團體與人物篩選。
   - 人物與全隊選項依 Google Sheet 原始列順序顯示。
   - 支援逐片選人、批量勾選套用、隨機人物欄位抽查與縮圖放大預覽。
   - 安全保留 YouTube 既有 categoryId、tags 等 metadata。

3. **🚀 YouTube 草稿發布與播放清單清理**
   - 讀取待發布 To-Post 播放清單，依上傳時間由早到晚處理。
   - 將影片切換為 `public` 後，自動自播放清單移除，不刪除頻道影片。
   - 顯示本應用程式估算的 YouTube Data API quota 使用量。

4. **📱 Instagram Reels 自動發布**
   - 從 Google Drive 資料夾依建立時間由早到晚讀取影片。
   - 使用與 YouTube 相同的 Sheet 團體／人物選擇邏輯，套用指定欄位的 Instagram 內文。
   - 下載 Drive 影片後上傳至 Cloudflare R2，驗證公開 HTTPS URL，再建立並發布 Reels。
   - 使用 **Instagram API with Instagram Login** 與 `graph.instagram.com`，不需連結 Facebook 粉絲專頁。
   - 支援逐片選人、批量套用、分享到動態消息、持久化工作結果與 retry。

---

## 📁 專案架構目錄

```text
creator-tools/
├── backend/
│   ├── app/
│   │   ├── api/              # auth, settings, sheets, youtube, instagram
│   │   ├── core/             # 環境變數、安全 Session、持久化設定
│   │   ├── services/         # Google、YouTube、Drive、R2、Instagram
│   │   └── main.py
│   ├── requirements.txt
│   └── tests/              # mock-only pytest tests
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
│   └── INSTAGRAM_R2_SETUP.md
├── .env.example
├── pyproject.toml
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

後端 Health Check：`http://localhost:8000/api/v1/health`

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
- [Instagram Reels API 與 Cloudflare R2 設定教學](docs/INSTAGRAM_R2_SETUP.md)
- [Docker 部署說明](docs/DEPLOYMENT.md)

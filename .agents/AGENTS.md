# 🤖 Project Guidelines & Agent Instructions

## 📋 專案概述 (Project Overview)
YouTube Creator Tools 是一個整合 Google Sheets API 與 YouTube Data API v3 的自動化控制台系統。
本專案採用 Python FastAPI 後端 + React Vite 前端 + Docker 容器化部署。

---

## 🏷️ Tagging & Release 規範 (Git Tagging & Release Logic)

1. **版本號格式**：採用語義化版本 `vX.Y.Z`（例如 `v1.0.0`, `v1.1.0`）。
2. **GHCR & Docker Image 建置**：
   - 每次 Push 至 `main` / `master` 分支或推送 Tag 時，GitHub Actions 會自動建置 Docker Image 並推送到 GHCR (`ghcr.io/minhung1126/creator-tools:latest`)。
3. **Automatic Release 條件**：
   - 僅當推送符合 `v*` 格式的 Git Tag 時（例如 `git tag v1.0.0 && git push origin v1.0.0`），GitHub Actions 才會自動觸發建立 GitHub Release。
   - 一般的分支 Commit / Merge **不會** 觸發 GitHub Release 建立（`if: startsWith(github.ref, 'refs/tags/v')`）。

---

## ⚠️ 開發與架構注意事項 (Developer Notice & Conventions)

### 1. 伺服器與 OAuth 設定 (`.env` & Config)
- **HOST 與 PORT 分離**：`.env` 只需指定 `HOST`（如 `localhost` 或域名）與 `PORT`（如 `8000`）。
- **網址自動計算**：後端會依據 `HOST` 自動判斷環境：
  - `localhost` / `127.0.0.1` → 自動使用 `http://` 協定，開放 `OAUTHLIB_INSECURE_TRANSPORT`
  - 其他正式域名 → 自動使用 `https://` 協定，強制啟用安全的 OAuth 傳輸與 `secure` Cookie
- **Credentials 管理**：Google Client ID 與 Client Secret **嚴禁** 由前端傳遞或於 UI 編輯，一律由後端 `.env` 檔案管理。

### 2. 設定持久化機制 (`data/runtime_config.json`)
- 使用者於「系統設定」頁面修改的預設 Sheet ID、Playlist ID、Drive Folder ID 以及 Meta API 設定，會由 `RuntimeConfig` 自動寫入 `data/runtime_config.json`。
- 啟動優先順序：`data/runtime_config.json` > `.env` 預設值。
- 在 Docker / Compose 環境中已將 `./data` 資料夾設定為 Volume (`./data:/app/data`) 進行持久化。

### 3. API 認證與安全規範
- 統一使用 `backend.app.core.dependencies.require_credentials` 作為 FastAPI Dependency。
- Session Cookie 採用 `itsdangerous` 進行全資料加密與簽章 (`creator_tools_session`)。
- Log 輸出統一使用標準 `logging` 模組，禁止於正式程式碼中使用 `print()`。

### 4. 前端 UI 規範
- 禁用原生 `alert()` 與 `confirm()`，一律使用 `useToast()` 通知與 `ConfirmDialog` 互動對話框。
- 保持暗色 Glassmorphism 設計語言，樣式與佈局優先使用 `index.css` 抽取的通用 class（如 `.glass-panel`, `.section-gap`, `.form-group`, `.btn`）。

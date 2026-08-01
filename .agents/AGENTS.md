# 🤖 Project Guidelines & Agent Instructions

## 📋 專案概述 (Project Overview)
Creator Tools 是一個整合 Google Sheets、YouTube、Instagram 與 Drive 的自動化控制台系統。
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
- **bind 與 public URL 分離**：`.env` 使用 `BIND_HOST`/`PORT` bind，使用 `PUBLIC_BASE_URL`/`FRONTEND_URL` 產生 OAuth callback；cookie `secure` 依 public URL scheme 判斷。
- **單一管理者**：正式環境必須設定 `ALLOWED_GOOGLE_EMAILS`，不在 allowlist 的 Google 帳號拒絕登入。
- **Credentials 管理**：Google Client ID 與 Client Secret **嚴禁** 由前端傳遞或於 UI 編輯，一律由後端 `.env` 檔案管理。

### 2. 設定持久化機制 (`data/runtime_config.json`)
- 使用者於頁面修改的非 secret 設定會由 `RuntimeConfig` 自動寫入 `data/runtime_config.json`；Instagram Token、R2 secret 與 Google token 分別加密保存。
- 啟動優先順序：`data/runtime_config.json` > `.env` 預設值。
- 在 Docker / Compose 環境中已將 `./data` 資料夾設定為 Volume (`./data:/app/data`) 進行持久化。

### 3. API 認證與安全規範
- 統一使用 `backend.app.core.dependencies.require_credentials` 作為 FastAPI Dependency。
- Session Cookie 只保存 opaque session ID；Google token 加密保存於 server-side session store。OAuth state 使用分離 salt 的 timed signature。
- Log 輸出統一使用標準 `logging` 模組，禁止於正式程式碼中使用 `print()`。

### 4. 前端 UI 規範
- 禁用原生 `alert()` 與 `confirm()`，一律使用 `useToast()` 通知與 `ConfirmDialog` 互動對話框。
- 保持暗色 Glassmorphism 設計語言，樣式與佈局優先使用 `index.css` 抽取的通用 class（如 `.glass-panel`, `.section-gap`, `.form-group`, `.btn`）。

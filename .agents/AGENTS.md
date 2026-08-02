# Creator Tools 開發規範

Creator Tools 使用 FastAPI、React/Vite 與 Docker，整合 Google Sheets 與 YouTube。

## 架構與安全

- OAuth bind 位址使用 `BIND_HOST`／`PORT`；callback URL 使用 `PUBLIC_BASE_URL`／`FRONTEND_URL`。
- 正式環境必須設定 `ALLOWED_GOOGLE_EMAILS`。
- Google Client ID、Client Secret 與所有 token／secret 只能由後端管理，不得傳至前端或寫入版本庫。
- 非 secret 執行期設定保存於 `data/runtime_config.json`，優先於 `.env` 預設值；`data/` 必須持久化。
- FastAPI 認證統一使用 `require_credentials`。正式程式使用 `logging`，不得使用 `print()`。

## 前端

- 禁止原生 `alert()`／`confirm()`；使用 `useToast()` 與 `ConfirmDialog`。
- 沿用暗色 Glassmorphism 與 `index.css` 的共用 class，避免重複 inline style。

## 驗證

- 後端：`python -m ruff check backend`、`python -m pytest backend/tests -q`
- 前端：`npm run lint`、`npm test -- --run`、`npm run build`

## Release
- 版本使用 `vX.Y.Z`。Push `main` 或 tag 會建置 GHCR image；只有 `v*` tag 會建立 GitHub Release。

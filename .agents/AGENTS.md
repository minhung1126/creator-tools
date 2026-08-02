# Creator Tools 開發規範

Creator Tools 使用 FastAPI、React/Vite 與 Docker，整合 Google Sheets、Drive、YouTube 和 Instagram。

## 架構與安全

- OAuth bind 位址使用 `BIND_HOST`／`PORT`；callback URL 使用 `PUBLIC_BASE_URL`／`FRONTEND_URL`。
- 正式環境必須設定 `ALLOWED_GOOGLE_EMAILS`。
- Google Client ID、Client Secret 與所有 token／secret 只能由後端管理，不得傳至前端或寫入版本庫。
- 非 secret 執行期設定保存於 `data/runtime_config.json`，優先於 `.env` 預設值；`data/` 必須持久化。
- FastAPI 認證統一使用 `require_credentials`。正式程式使用 `logging`，不得使用 `print()`。

## Instagram API 硬性規則

- 本專案使用 **Instagram API with Instagram Login**：host 是 `graph.instagram.com`，憑證是 Instagram User access token。不得與 `graph.facebook.com` 或 Facebook User／Page token 混用。
- **禁止 Instagram Graph batch requests**：不得送出 `batch` payload、`depends_on` child request，也不得 POST 至 `https://graph.instagram.com/{version}` 根路徑進行批次操作。
- Reels 必須逐支處理，每個 worker 一次只 claim 一支影片，並依序呼叫：
  1. `POST /{ig_user_id}/media`
  2. `GET /{creation_id}`，直到處理完成
  3. `POST /{ig_user_id}/media_publish`
- 每支影片取得 `creation_id` 或 `media_id` 後必須立即保存 checkpoint；重試不得重建或重發已確認成功的外部操作。
- 多支影片仍可屬於同一使用者批次，但只能依 queue 順序逐支執行。若單支失敗，依既有 failure policy 暫停後續項目。
- 除非專案正式切換登入產品，且 Meta 官方文件明確證實該 host/token 組合支援 batch，否則不得重新加入 batch 實作。

## 前端

- 禁止原生 `alert()`／`confirm()`；使用 `useToast()` 與 `ConfirmDialog`。
- 沿用暗色 Glassmorphism 與 `index.css` 的共用 class，避免重複 inline style。

## 驗證

- 後端：`python -m ruff check backend`、`python -m pytest backend/tests -q`
- 前端：`npm run lint`、`npm test -- --run`、`npm run build`
- Instagram 相關修改必須測試：不含 `batch` payload、一次只 dispatch 一支任務、checkpoint 可安全重試。

## Release

- 版本使用 `vX.Y.Z`。Push `main` 或 tag 會建置 GHCR image；只有 `v*` tag 會建立 GitHub Release。

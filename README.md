# Creator Tools

Creator Tools 是以 FastAPI 與 React/Vite 建置的創作者工作流控制台，使用 Google OAuth 讀取 Google Sheets，並管理 YouTube 草稿、影片資訊更新、發布與播放清單清理。登入 session、帳號工作狀態、加密憑證與 YouTube 配額估算會保存於伺服器端 `data/`。

## 目前功能

- Google 控制台登入與 Google Sheets 設定
- YouTube 主要／次要授權組合、頻道驗證與作用中授權切換
- YouTube Auto routing：Primary quota 足夠時優先使用 Primary，不足時由新的 workflow 選用 Secondary
- Video／Shorts 草稿的工作表欄位設定、人物篩選與影片資訊更新
- To-Post 播放清單讀取、依上傳時間發布並移出播放清單
- YouTube Data API 配額估算、安全上限與每個授權組合的 ledger

YouTube API 工作流在 API 請求內執行並直接回傳結果。預設 Auto routing 會在每個 workflow 開始時以保守 quota 預估選擇 Primary 或 Secondary；同一個 preview／批次執行期間固定使用所選 slot，不會中途切換或建立背景重試工作。需要時可在 YouTube 設定切換為手動模式。

## 操作安全與錯誤處理

- 公開／移出清單與批次覆寫都必須先讀取並顯示完整預覽；執行請求會帶入後端簽署的短效 token。
- 後端在任何寫入前重新驗證帳號、YouTube slot、播放清單、試算表與影片 metadata；資料變更時回傳 `409 stale_preview`，不執行任何寫入。
- YouTube 預設播放清單與每個 slot 的 quota 使用分離 API 與儲存動作；播放清單可填 ID 或 YouTube URL。
- API 錯誤固定為 `detail.code`、`detail.message`、`detail.retryable`、`detail.field_errors`，provider 原始回應與 token 不會回傳前端。

## 操作安全與錯誤處理

- 公開／移出清單與批次覆寫都必須先讀取並顯示完整預覽；執行請求會帶入後端簽署的短效 token。
- 後端在任何寫入前重新驗證帳號、YouTube slot、播放清單、試算表與影片 metadata；資料變更時回傳 `409 stale_preview`，不執行任何寫入。
- YouTube 預設播放清單與每個 slot 的 quota 使用分離 API 與儲存動作；播放清單可填 ID 或 YouTube URL。
- API 錯誤固定為 `detail.code`、`detail.message`、`detail.retryable`、`detail.field_errors`，provider 原始回應與 token 不會回傳前端。

## 專案結構

```text
backend/app/main.py       FastAPI 應用程式與健康檢查
backend/app/api/          auth、settings、sheets、youtube 路由
backend/tests/            後端測試
frontend/src/             React 應用程式、元件與頁面
docs/                     OAuth、配額與部署文件
data/                     執行期資料，不提交至 Git
Dockerfile                前端建置與 FastAPI production image
docker-compose.yml        本機／部署用 Compose 設定
```

## 本機開發

先複製環境範例並填入本機值。`ALLOWED_GOOGLE_EMAILS` 必須改成實際允許登入的 Google 帳號；空值只適合本機開發，不適合正式環境。

```powershell
copy .env.example .env

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements-dev.txt
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

另一個終端機啟動前端：

```powershell
cd frontend
npm ci
npm run dev
```

開啟 <http://localhost:3000>。後端健康檢查為 <http://localhost:8000/api/v1/health>；除 HTTP 200 外，也請確認 JSON 的 `ready` 是否為 `true`。

## 驗證

```powershell
cd frontend
npm run lint
npm test -- --run
npm run build

cd ..
python -m ruff format --check backend
python -m ruff check backend
python -m pytest -q
docker compose config
```

若要執行 Compose，根目錄必須存在 `.env`：

```powershell
copy .env.example .env
docker compose up -d --build
docker compose ps
```

Compose 預設把容器的 8000 port 綁到本機 `127.0.0.1:${HOST_PORT}`，並以 `./data:/app/data` 保存執行期資料。

## 文件

- [Google API 與 OAuth 設定](docs/GOOGLE_API_SETUP.md)
- [YouTube 配額說明](docs/YOUTUBE_QUOTA.md)
- [Docker 與 production 部署](docs/DEPLOYMENT.md)

正式環境請固定保存 `SECRET_KEY` 與 `CREDENTIAL_ENCRYPTION_KEY`，設定 `PUBLIC_BASE_URL`、`FRONTEND_URL`、`ALLOWED_GOOGLE_EMAILS` 及 Google／YouTube OAuth 憑證。Google callback 由 `PUBLIC_BASE_URL` 組成：`/api/v1/auth/callback`。

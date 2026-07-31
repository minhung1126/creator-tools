# Google API 申請與 OAuth 2.0 設定教學 (Google API Setup Guide)

本教學指引您如何在 **Google Cloud Console** 中建立專案、啟用必要的 APIs (Google Sheets, YouTube Data API v3, Google Drive)，並取得 `Client ID` 與 `Client Secret` 供本系統進行 OAuth 2.0 認證。

---

## 第一步：建立 Google Cloud 專案

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。
2. 點擊頂端專案選單，選擇 **「新增專案 (New Project)」**。
3. 輸入專案名稱（如 `YouTube-Creator-Tools`），點擊 **「建立 (Create)」**。

---

## 第二步：啟用必要的 Google APIs

進入專案控制台，在左側選單點擊 **「API 和服務」>「已啟用的 API 和服務」**，並點擊 **「+ 啟用 API 和服務」**：

1. **Google Sheets API**：
   - 在搜尋列輸入 `Google Sheets API`，點擊並按下 **「啟用 (Enable)」**。
2. **YouTube Data API v3**：
   - 在搜尋列輸入 `YouTube Data API v3`，點擊並按下 **「啟用 (Enable)」**。
3. **Google Drive API**：
   - 在搜尋列輸入 `Google Drive API`，點擊並按下 **「啟用 (Enable)」**。

---

## 第三步：設定 OAuth 同意畫面 (OAuth Consent Screen)

1. 在左側選單點擊 **「API 和服務」>「OAuth 同意畫面」**。
2. User Type 選擇 **「外部 (External)」**，點擊 **「建立」**。
3. 填寫基本資訊：
   - **應用程式名稱**：`YouTube Creator Tools`
   - **使用者支援電子郵件**：選擇您的 Email
   - **開發人員聯絡資訊**：填入您的 Email
4. 點擊 **「儲存並繼續」**。
5. **範圍 (Scopes)**：點擊 **「新增或移除範圍」**，勾選：
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `.../auth/spreadsheets.readonly` (Google Sheets 讀取權限)
   - `.../auth/youtube` (YouTube 完整管理權限)
   - `.../auth/drive.readonly` (Google Drive 讀取權限)
6. **測試使用者 (Test Users)**：新增您的 Google 帳號 Email，確保開發測試階段可登入。

---

## 第四步：建立 OAuth 2.0 憑證 (Client ID & Client Secret)

1. 在左側選單點擊 **「憑證 (Credentials)」**。
2. 點擊頂端 **「+ 建立憑證」>「OAuth 用戶端 ID (OAuth client ID)」**。
3. 應用程式類型選擇 **「網頁應用程式 (Web application)」**。
4. 名稱：`Creator Tools Web Client`
5. **已授權的重導向 URI (Authorized redirect URIs)**：
   - 點擊 **「新增 URI」**，輸入包含您的 HOST 設定之 API Callback 網址：
   
   *本地測試範例：*
   ```
   http://localhost:8000/api/v1/auth/callback
   ```
   
   *正式部署範例：*
   ```
   http://your-domain.com:8000/api/v1/auth/callback
   ```

6. 點擊 **「建立」**。系統彈出方塊，顯示您的：
   - **用戶端 ID (Client ID)**
   - **用戶端密碼 (Client Secret)**

---

## 第五步：將憑證寫入後端 `.env` 檔案

取得 Client ID 與 Client Secret 後，出於資安防護考量，**敏感憑證嚴禁由前端傳輸或於 Web UI 中編輯**，請統一於專案根目錄下的 `.env` 檔案進行設定：

在專案根目錄 `.env` 檔案中填入：
```env
# 伺服器主機名稱與通訊埠
HOST=localhost
PORT=8000

# Google OAuth 2.0 Client 憑證
GOOGLE_CLIENT_ID=1234567890-xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxx
```

> 💡 **小貼士：**
> - **持久化設定 (`runtime_config.json`)**：其他的業務預設值（例如預設 Google Sheet ID、Playlist ID、Drive Folder ID 以及 Meta API 金鑰），則可以隨時於系統 Web UI 的 **「系統與帳號設定」** 頁面進行動態修改，系統會自動將設定持久化儲存至根目錄的 `runtime_config.json` 中。
> - 修改 `.env` 設定檔後，請重新啟動後端服務或 Docker 容器以確保新環境變數生效。

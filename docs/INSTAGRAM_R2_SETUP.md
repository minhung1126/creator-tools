# Instagram Reels API 與 Cloudflare R2 設定教學

本教學說明如何讓 Creator Tools 從 Google Drive 取得影片、上傳到 Cloudflare R2，再用 **Instagram API with Instagram Login** 自動發布 Reels。此新版流程直接使用 Instagram 專業帳號，**不需要連結 Facebook 粉絲專頁**。

> 本專案使用 `graph.instagram.com`，不是舊的 Instagram Basic Display API，也不是需要 Facebook Page 的 Instagram API with Facebook Login。

---

## 一、開始前確認

### Instagram 帳號

- 必須是 Instagram **Business** 或 **Creator** 專業帳號。
- Personal 個人帳號不能使用內容發布 API。
- 需要權限：
  - `instagram_business_basic`
  - `instagram_business_content_publish`

### Google

Google OAuth 必須包含：

- `https://www.googleapis.com/auth/drive.readonly`
- `https://www.googleapis.com/auth/spreadsheets.readonly`

Google Sheet 至少要有以下欄位：

```text
所屬團體 | 人 | Instagram Caption
```

`人` 留空的資料列會作為「全隊」選項。

### Cloudflare R2

需要：

- 一個 R2 bucket。
- 限定該 bucket 的 Object Read & Write S3 API Token。
- 一個外網可直接存取的公開 HTTPS URL。

正式環境建議使用 R2 Custom Domain；`r2.dev` 適合測試，但有速率限制。

---

# 二、建立 Meta App

## 1. 將 Instagram 切換成專業帳號

在 Instagram App：

1. 開啟個人檔案。
2. 進入「設定和隱私」。
3. 找到「帳號類型和工具」。
4. 選擇「切換為專業帳號」。
5. 選擇 Creator 或 Business。

## 2. 建立 Meta App

1. 前往 [Meta for Developers](https://developers.facebook.com/apps/)。
2. 點擊 **Create App**。
3. 選擇可支援 Instagram API 的用途；若介面要求 App 類型，選擇 **Business**。
4. 填入 App 名稱與聯絡 Email。
5. 建立後進入 App Dashboard。

## 3. 加入 Instagram API with Instagram Login

1. 在 App Dashboard 找到 **Add products to your app**。
2. 選擇 **Instagram** 並按 **Set up**。
3. 進入 **API setup with Instagram login**。
4. 確認 API Host 為：

```text
https://graph.instagram.com
```

Creator Tools 預設 API Version：

```text
v25.0
```

日後 Meta 停用版本時，可在系統的 Instagram 設定頁修改。

## 4. 加入自己的 Instagram 測試帳號

App 在 Development Mode 時，只有 App 角色或測試帳號能使用尚未通過審查的權限。

1. 找到 **App roles / Roles / Instagram testers**。
2. 加入要發布 Reels 的 Instagram 專業帳號。
3. 使用該 Instagram 帳號接受測試邀請。
4. 確認帳號出現在 App 可使用的 Instagram Accounts 清單。

只供自己使用時，可先用自己的專業帳號作為測試帳號。若未來讓其他使用者連線，需依 Meta 規定申請 Advanced Access 與 App Review。

## 5. 開啟必要權限

需要：

```text
instagram_business_basic
instagram_business_content_publish
```

不要使用舊 scope：

```text
business_basic
business_content_publish
```

## 6. 產生 Instagram User Access Token

在 Meta App Dashboard 的 Instagram API 設定區：

1. 找到 **Generate access tokens**。
2. 選擇剛加入的 Instagram 專業帳號。
3. 授權 `instagram_business_basic`。
4. 授權 `instagram_business_content_publish`。
5. 產生並複製 Instagram User Access Token。

Token 是敏感資料，不要放進 Git、README、截圖或公開訊息。

> Creator Tools 目前使用手動貼入 Token 的方式。Token 過期或被撤銷時，需要重新產生並更新設定。

## 7. 取得 Instagram User ID

使用以下指令：

```bash
curl -G "https://graph.instagram.com/v25.0/me" \
  --data-urlencode "fields=id,username,account_type" \
  --data-urlencode "access_token=YOUR_INSTAGRAM_ACCESS_TOKEN"
```

預期回傳：

```json
{
  "id": "17841400000000000",
  "username": "your_instagram_account",
  "account_type": "CREATOR"
}
```

把 `id` 填入 Creator Tools 的 **Instagram User ID**。

若回傳權限錯誤，確認：

- 帳號是 Business 或 Creator。
- 帳號已接受 App 測試邀請。
- Token 包含 `instagram_business_basic`。
- 使用的是 `graph.instagram.com`，不是 `graph.facebook.com`。

## 8. 取得 App ID 與 App Secret

在 Meta App Dashboard 的 **App settings > Basic**：

- 複製 App ID。
- 顯示並複製 App Secret。

目前實際發布主要使用 Instagram User ID 與 Access Token；App Secret 保留給之後的 Instagram OAuth／Token 更新功能。

---

# 三、建立 Cloudflare R2

## 1. 建立 Bucket

1. 登入 [Cloudflare Dashboard](https://dash.cloudflare.com/)。
2. 進入 **Storage & databases > R2 Object Storage**。
3. 點擊 **Create bucket**。
4. 建議名稱：

```text
creator-tools-media
```

5. 建立後記下 Bucket Name。

Bucket 預設是私有的，後面仍需設定公開網域，Instagram 才能抓取影片。

## 2. 建立 R2 S3 API Token

1. 在 R2 Overview 找到 **API Tokens**。
2. 點擊 **Manage**。
3. 建立 Account API Token 或 User API Token。
4. 權限選擇：

```text
Object Read & Write
```

5. 建議限制只存取 Creator Tools 使用的 bucket。
6. 建立後立即複製：
   - Access Key ID
   - Secret Access Key

Secret Access Key 通常只顯示一次。

R2 S3 Endpoint 格式：

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

Creator Tools 會用 Account ID 自動組合 Endpoint，region 使用 `auto`。

## 3. 取得 Cloudflare Account ID

可在 R2 Overview 的 Account Details 或 Cloudflare 網站 Overview 找到。

Account ID 類似：

```text
0123456789abcdef0123456789abcdef
```

不要誤填 Zone ID。

## 4. 設定公開 HTTPS URL

Instagram 不會拿你的 R2 S3 金鑰抓影片，只能從公開 `video_url` 下載。

### 正式環境：Custom Domain

1. 進入 R2 bucket。
2. 選擇 **Settings**。
3. 在 **Custom Domains** 點擊 **Add**。
4. 輸入例如：

```text
media.example.com
```

5. 等待狀態變成 Active。
6. Creator Tools 的 R2 Public Base URL 填：

```text
https://media.example.com
```

### 測試環境：r2.dev

1. 進入 bucket 的 **Settings**。
2. 找到 **Public Development URL**。
3. 點擊 Enable。
4. 依畫面確認開啟公開存取。
5. 填入顯示的 URL，例如：

```text
https://pub-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.r2.dev
```

## 5. 驗證公開網址

手動上傳一個小檔案，例如 `test.txt`，再開啟：

```text
https://你的公開網域/test.txt
```

必須在沒有登入、Cookie 或 Authorization Header 的情況下直接取得檔案。

不要在提供給 Instagram 的路徑套用 Cloudflare Access 登入或其他需要授權的保護。

---

# 四、填入 Creator Tools

進入：

```text
平台設定 > Instagram / R2 設定
```

## Instagram 欄位

| 欄位 | 值 | 必要 |
|---|---|---|
| Instagram App ID | Meta App Dashboard 的 App ID | 建議 |
| Instagram User ID | `/me` 回傳的 `id` | 必填 |
| Graph API Version | 預設 `v25.0` | 必填 |
| Instagram App Secret | Meta App Secret | 選填／預留 |
| Instagram User Access Token | 含發布權限的 Token | 必填 |

## R2 欄位

| 欄位 | 值 | 必要 |
|---|---|---|
| R2 Account ID | Cloudflare Account ID | 必填 |
| R2 Bucket Name | Bucket 名稱 | 必填 |
| R2 Access Key ID | S3 Token Access Key ID | 必填 |
| R2 Secret Access Key | S3 Token Secret | 必填 |
| R2 Public Base URL | Custom Domain 或 r2.dev URL | 必填 |

Public Base URL 不要加結尾 `/`。

儲存後按「測試 Instagram 與 R2 連線」。測試會：

1. 用 Instagram Token 讀取 `id`、`username`、`account_type`。
2. 用 R2 S3 憑證檢查 bucket。

---

# 五、設定 Google Drive 與 Google Sheet

## Drive 資料夾

Google 設定中填入 Drive 資料夾 URL 或 ID：

```text
https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp
```

或：

```text
1AbCdEfGhIjKlMnOp
```

Instagram Reels 頁會依 Google Drive `createdTime` 由早到晚列出影片。

## Sheet 範例

```text
所屬團體 | 人     | Instagram Caption
QWER     | 쵸단   | 內文... #QWER #쵸단
QWER     | 마젠타 | 內文... #QWER #마젠타
QWER     |        | 全隊內文... #QWER
```

人物與全隊選項會遵守 Sheet 原始列順序。

---

# 六、實際發布流程

進入：

```text
Instagram > Reels 自動上傳
```

操作順序：

1. 選擇 Google Drive 資料夾。
2. 選擇 Google Sheet、工作表與 Instagram 內文欄位。
3. 選擇團體與人物。
4. 讀取 Drive 影片。
5. 逐片選人，或勾選多支影片後批量套用人物。
6. 選擇是否分享到動態消息。
7. 儲存流程設定。
8. 按正式發布並再次確認。

後端流程：

```text
Drive 下載影片
→ 上傳 R2
→ 驗證公開 URL
→ 建立 Instagram Reels Container
→ 輪詢等待 FINISHED
→ 呼叫 media_publish 正式發布
```

為方便除錯，發布後不會立即刪除 R2 物件。

---

# 七、影片規格建議

建議：

- Container：MP4 或 MOV。
- Video codec：H.264 或 HEVC。
- Audio codec：AAC，48 kHz。
- Frame rate：23–60 FPS。
- 建議比例：9:16。
- 水平像素不超過 1920。
- Video bitrate 不超過 25 Mbps。
- Audio bitrate 約 128 kbps。
- 長度：3 秒至 15 分鐘。
- 檔案大小：不超過 1 GB。

---

# 八、R2 清理建議

建議物件路徑：

```text
instagram-reels/YYYY/MM/DD/...
```

可在 R2 設定 Lifecycle，自動刪除 7–30 天前的物件。不要設定太短，Instagram 建立 Container 時仍需抓取影片。

---

# 九、常見錯誤

## Instagram 權限不足

確認：

- Token 有 `instagram_business_basic`。
- Token 有 `instagram_business_content_publish`。
- 沒有誤用舊 scope。
- 帳號是 Business／Creator。
- Development Mode 下帳號已加入並接受測試角色。

## 找不到 Instagram User ID

使用：

```bash
curl -G "https://graph.instagram.com/v25.0/me" \
  --data-urlencode "fields=id,username,account_type" \
  --data-urlencode "access_token=YOUR_TOKEN"
```

不要把 Instagram 使用者名稱、Facebook Page ID 或 Meta App ID 當成 User ID。

## R2 連線成功但 Instagram 抓不到影片

R2 Token 可用只代表後端能上傳，不代表網址公開。確認：

- Public Base URL 使用 `https://`。
- 無痕視窗可直接下載檔案。
- URL 沒有 Cloudflare Access 登入頁。
- Custom Domain 已 Active。
- r2.dev 已開啟 Public Access。

## Container 一直處理中

確認：

- URL 公開可讀。
- 影片是有效 MP4／MOV。
- 編碼、FPS、bitrate、長度與大小符合規格。
- R2 物件沒有太早被刪除。

## Token 後來失效

Token 可能過期、被撤銷，或因密碼／權限調整失效。Creator Tools 目前不會自動更新 Instagram Token，請重新產生並在設定頁更新。

---

# 十、資安注意事項

- 不要把 Instagram Token、App Secret、R2 Secret Access Key 提交到 Git。
- R2 Token 只授權需要的單一 bucket。
- 敏感欄位儲存在後端 `data/runtime_config.json`，設定 API 不會回傳完整 secret/token。
- 限制 `data/` 目錄的主機存取權限。
- 正式環境務必修改 `.env` 的 `SECRET_KEY`。

---

# 官方參考資料

- [Meta 官方 Instagram API Postman Workspace](https://www.postman.com/meta/instagram/overview)
- [Cloudflare R2 S3 API](https://developers.cloudflare.com/r2/get-started/s3/)
- [Cloudflare R2 API Tokens](https://developers.cloudflare.com/r2/api/tokens/)
- [Cloudflare R2 Public Buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)

# Instagram Reels API、Instagram Login 與 Cloudflare R2 設定教學

Creator Tools 使用 **Instagram API with Instagram Login**。Instagram 專業帳號不必連結 Facebook 粉絲專頁；正常使用流程也不需要手動複製 Access Token 或查詢 User ID。

## 1. 前置條件

- Instagram 帳號必須是 Business 或 Creator 專業帳號。
- 必要權限：`instagram_business_basic`、`instagram_business_content_publish`。
- Google OAuth 需有 Drive readonly 與 Sheets readonly。
- R2 需有可公開存取的 HTTPS URL；正式環境建議 Custom Domain。

## 2. 建立 Meta App

1. 在 Meta for Developers 建立 App。
2. 加入 Instagram，選擇 **API setup with Instagram login**。
3. Development Mode 下，把自己的 Instagram 專業帳號加入測試角色並接受邀請。
4. 僅要求：

```text
instagram_business_basic
instagram_business_content_publish
```

舊 scope `business_basic`、`business_content_publish` 不適用。

## 3. 設定 OAuth Redirect URI

先在 Creator Tools 的 Instagram / R2 設定頁查看系統顯示的 Redirect URI，例如：

```text
https://creator.example.com/api/v1/instagram/auth/callback
```

將它完整填入 Meta App 的 **Valid OAuth Redirect URIs**。協定、網域、port、path 與結尾斜線都必須完全一致。

## 4. 設定伺服器環境變數

```env
INSTAGRAM_APP_ID=你的 App ID
INSTAGRAM_APP_SECRET=你的 App Secret
INSTAGRAM_REDIRECT_URI=https://creator.example.com/api/v1/instagram/auth/callback
CREDENTIAL_ENCRYPTION_KEY=固定且足夠長的隨機字串
INSTAGRAM_API_VERSION=v25.0
```

`INSTAGRAM_API_VERSION` 是可調整的預設值，不代表文件永久宣稱它是 Meta 最新版本。

`CREDENTIAL_ENCRYPTION_KEY` 一旦開始儲存憑證後不要更換；更換後舊 Token 將無法解密，必須重新連線。

## 5. 在 Creator Tools 連接 Instagram

1. 使用 Google 登入 Creator Tools。
2. 前往 **Instagram > Instagram / R2 設定**。
3. 按 **使用 Instagram 登入並授權**。
4. 在 Instagram 登入並同意必要權限。
5. 完成後系統會自動：
   - 驗證 OAuth `state`。
   - 交換短期 Token。
   - 換成長效 Token。
   - 呼叫 `/me` 取得 Instagram User ID、username、account type。
   - 將 Token 加密儲存在 `data/credential_store.json`。
   - 回到設定頁顯示連線帳號與到期時間。

Access Token 不會回傳前端，也不會放在 URL。

設定頁提供：

- 重新授權／切換帳號
- 更新 Token
- 中斷連線並刪除本機 Token

發布前若 Token 接近到期，系統會嘗試更新；更新失敗時會停止發布並要求重新連線。

## 6. Cloudflare R2

1. 建立 R2 bucket。
2. 建立限制於該 bucket 的 Object Read & Write S3 API Token。
3. 記下 Account ID、Access Key ID、Secret Access Key、Bucket Name。
4. 建立 Custom Domain，或測試時啟用 `r2.dev` Public Development URL。
5. 在 Instagram / R2 設定頁輸入 R2 欄位並按 **測試 R2**。

R2 Endpoint 由系統組成：

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

region 使用 `auto`。Secret Access Key 與 Instagram Token 一樣加密儲存。

## 7. Google Drive 與 Sheet

Sheet 至少包含：

```text
所屬團體 | 人 | Instagram Caption
```

`人` 空白列作為全隊選項。人物與全隊順序遵守 Sheet 原始列順序。

Reels 頁依 Drive `createdTime` 由舊到新處理影片：

```text
Drive 下載
→ 上傳 R2
→ 驗證公開 URL
→ 建立 Reels container
→ 等待 FINISHED
→ media_publish
```

第一支發布失敗後，後續影片會暫停，避免順序錯亂。

## 8. 手動診斷（非正常設定流程）

只有 OAuth 故障排除時才需要手動測試：

```bash
curl -G "https://graph.instagram.com/v25.0/me" \
  --data-urlencode "fields=id,username,account_type" \
  --data-urlencode "access_token=YOUR_TOKEN"
```

不要把 Token 放入 Git、README、截圖或公開訊息。

## 9. 常見問題

- **redirect_uri 不相符**：確認 Meta 後台與設定頁顯示值逐字一致。
- **帳號無法授權**：確認是專業帳號，且 Development Mode 下已接受測試邀請。
- **權限不足**：確認使用新的 `instagram_business_*` scopes。
- **重新啟動後連線消失**：確認 Docker 有掛載 `./data:/app/data`。
- **無法解密憑證**：確認 `CREDENTIAL_ENCRYPTION_KEY` 沒有被更換。
- **Instagram 抓不到影片**：R2 URL 必須可在無 Cookie、無 Authorization 的情況下公開下載。

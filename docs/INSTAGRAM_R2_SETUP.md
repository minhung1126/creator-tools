# Instagram Reels API、Instagram Login 與 Cloudflare R2 設定教學

Creator Tools 使用 Instagram API with Instagram Login。Instagram 專業帳號不必連結 Facebook 粉絲專頁。

## 1. Meta App 與 OAuth

- 帳號必須是 Business 或 Creator 專業帳號。
- Required scopes：`instagram_business_basic`、`instagram_business_content_publish`。
- Development Mode 下，把測試帳號加入測試角色並接受邀請。
- 在 Meta App 的 Valid OAuth Redirect URIs 填入：`PUBLIC_BASE_URL/api/v1/instagram/auth/callback`。

```env
INSTAGRAM_APP_ID=你的 App ID
INSTAGRAM_APP_SECRET=你的 App Secret
PUBLIC_BASE_URL=https://creator.example.com
FRONTEND_URL=https://creator.example.com
ALLOWED_GOOGLE_EMAILS=admin@example.com
CREDENTIAL_ENCRYPTION_KEY=固定且足夠長的隨機字串
```

Instagram API version 由後端 release pin，不能由 UI 任意修改；callback 只由 `PUBLIC_BASE_URL` 產生。

完成 OAuth 後，Token 會加密存於 `data/credential_store.json`，不會回傳前端或放在 URL。Meta 沒有回傳 permissions 時，設定頁顯示「未提供／尚未驗證」，不會自行宣稱 required scopes 已授權。

## 2. Cloudflare R2

1. 建立 R2 bucket 與限制於該 bucket 的 Object Read & Write S3 API token。
2. 在 Instagram / R2 設定頁輸入 Account ID、Access Key ID、Bucket Name、HTTPS public base URL 與 Secret Access Key。
3. Secret Access Key 只能由 UI 輸入並加密存入 credential store，不支援 env/UI 雙來源。
4. public base URL 必須 HTTPS，系統會拒絕 localhost/private IP；建議使用 Custom Domain 或 `r2.dev`。
5. 為 `instagram-reels/` prefix 設定 1–7 天 lifecycle，預設工作流程使用 3 天，避免影片永久堆積。

Reel 成功發布後，工作流程會立即刪除該支影片的 R2 object；lifecycle 仍作為清理失敗或中斷工作的後備保護。若刪除暫時失敗，工作會保留 `published` 狀態並提供重試清理，不會重複發布 Instagram 影片。

Endpoint：

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

## 3. Reels 工作流程

Drive list 使用 pagination 與 `videoMediaMetadata` 做 size、duration、dimensions preflight。發布工作透過：

```text
POST /api/v1/instagram/publish-jobs
GET  /api/v1/instagram/publish-jobs/{id}
POST /api/v1/instagram/publish-jobs/{id}/retry
```

每片會保存 `queued`、`uploaded`、`container_created`、`published`、`failed`、`paused` 與 creation/media ID。第一片失敗會暫停後續；retry 會沿用已保存的 creation ID。結果保存於 `data/instagram_publish_jobs.json`。

Sheet 至少包含：

```text
所屬團體 | 人 | Instagram Caption
```

## 4. 常見問題

- redirect_uri 不相符：確認 Meta 後台與設定頁顯示值逐字一致。
- 無法解密憑證：確認 `CREDENTIAL_ENCRYPTION_KEY` 沒有被更換。
- R2 抓不到影片：確認 public URL 可在無 Cookie、無 Authorization 的情況下下載。
- 真實帳號驗收前，請先完成 App ID、App Secret、Redirect URI 與測試帳號設定；自動測試只使用 mock。

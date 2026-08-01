import React, { useState } from 'react';
import { api } from '../services/api';
import { 
  Video, 
  LogIn, 
  CheckCircle2, 
  AlertCircle, 
  Lock
} from 'lucide-react';

export default function LoginPage({ initialError }) {
  const [loggingIn, setLoggingIn] = useState(false);
  const [errorMsg, setErrorMsg] = useState(initialError || null);

  const handleGoogleLogin = async () => {
    setLoggingIn(true);
    setErrorMsg(null);
    try {
      const res = await api.getAuthUrl();
      if (res && res.auth_url) {
        window.location.href = res.auth_url;
      } else {
        setErrorMsg('無法取得 Google 授權網址，請確認後端設定。');
        setLoggingIn(false);
      }
    } catch (err) {
      console.error('Google auth error:', err);
      setErrorMsg(err.message || '連線至 Google 授權服務失敗，請確認 .env 設定。');
      setLoggingIn(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card glass-panel">
        {/* Header Branding */}
        <div className="login-header">
          <div className="login-logo-box">
            <Video size={36} color="#ffffff" />
          </div>
          <h1 className="login-title">YouTube Creator Tools</h1>
          <p className="login-subtitle">創作者自動化控制台系統</p>
        </div>

        {/* Security Badge */}
        <div className="login-badge">
          <Lock size={14} /> 需要授權存取
        </div>

        {/* Description */}
        <p className="login-description">
          歡迎使用 YouTube Creator Tools。開啟控制台與內部功能前，請先登入 Google 帳號授權存取對應之 API 資源。
        </p>

        {/* Feature List */}
        <div className="login-features">
          <div className="feature-item">
            <CheckCircle2 size={18} className="feature-icon" />
            <span>整合 <strong>Google Sheets API</strong> 自動讀取影片標題與對照資料</span>
          </div>
          <div className="feature-item">
            <CheckCircle2 size={18} className="feature-icon" />
            <span>整合 <strong>YouTube Data API v3</strong> 批次更新與發布管理</span>
          </div>
          <div className="feature-item">
            <CheckCircle2 size={18} className="feature-icon" />
            <span>安全的 <strong>Session Cookie</strong> 加密傳輸與憑證管理</span>
          </div>
        </div>

        {/* Error Alert */}
        {errorMsg && (
          <div className="login-error-alert">
            <AlertCircle size={18} />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Login Action Button */}
        <div className="login-actions">
          <button 
            className="btn btn-primary login-btn"
            onClick={handleGoogleLogin}
            disabled={loggingIn}
          >
            {loggingIn ? (
              <>
                <span className="login-spinner"></span>
                正在傳送至 Google 授權...
              </>
            ) : (
              <>
                <LogIn size={20} />
                使用 Google 帳號登入
              </>
            )}
          </button>
        </div>

        <p className="login-footer">
          點擊登入即代表透過 Google OAuth 2.0 授權本系統存取必要權限
        </p>
      </div>
    </div>
  );
}

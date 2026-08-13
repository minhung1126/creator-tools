import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';
import { 
  Video, 
  LogIn, 
  CheckCircle2, 
  AlertCircle, 
  Lock,
  RefreshCw,
} from 'lucide-react';

export default function LoginPage({ initialError }) {
  const [loggingIn, setLoggingIn] = useState(false);
  const [oauthError, setOauthError] = useState(initialError || null);
  const [readinessError, setReadinessError] = useState(null);
  const [authConfig, setAuthConfig] = useState(null);
  const [checkingConfig, setCheckingConfig] = useState(true);

  const checkLoginReadiness = useCallback(async () => {
    setCheckingConfig(true);
    try {
      const config = await api.getAuthConfig();
      setAuthConfig(config);
      if (!config.has_client_id || !config.has_client_secret) {
        setReadinessError('Google 登入尚未完成系統設定，請聯絡管理者補齊 OAuth 憑證。');
      } else {
        setReadinessError(null);
      }
    } catch (error) {
      setAuthConfig(null);
      setReadinessError(error.message || '無法檢查 Google 登入服務狀態，請稍後重試。');
    } finally {
      setCheckingConfig(false);
    }
  }, []);

  useEffect(() => { checkLoginReadiness(); }, [checkLoginReadiness]);

  const handleGoogleLogin = async () => {
    setLoggingIn(true);
    setOauthError(null);
    try {
      const res = await api.getAuthUrl();
      if (res && res.auth_url) {
        window.location.href = res.auth_url;
      } else {
        setOauthError('無法取得 Google 授權網址，請確認後端設定。');
        setLoggingIn(false);
      }
    } catch (err) {
      console.error('Google auth error:', err);
      setOauthError(err.message || '連線至 Google 授權服務失敗，請稍後重試。');
      setLoggingIn(false);
    }
  };

  const loginReady = Boolean(authConfig?.has_client_id && authConfig?.has_client_secret);

  return (
    <div className="login-container">
      <div className="login-card glass-panel">
        {/* Header Branding */}
        <div className="login-header">
          <div className="login-logo-box">
            <Video size={36} color="var(--text-main)" />
          </div>
          <h1 className="login-title">Creator Tools</h1>
          <p className="login-subtitle">創作者自動化控制台系統</p>
        </div>

        {/* Security Badge */}
        <div className="login-badge">
          <Lock size={14} /> 需要授權存取
        </div>

        {/* Description */}
        <p className="login-description">
          歡迎使用 Creator Tools。開啟控制台與共用 Google Sheet 功能前，請先登入控制台 Google 帳號；YouTube 頻道授權會在登入後的 YouTube 設定頁另外管理。
        </p>

        {/* Feature List */}
        <div className="login-features">
          <div className="feature-item">
            <CheckCircle2 size={18} className="feature-icon" />
            <span>以 <strong>Google Sheets API 唯讀權限</strong> 讀取影片標題與對照資料</span>
          </div>
          <div className="feature-item">
            <CheckCircle2 size={18} className="feature-icon" />
            <span><strong>YouTube 頻道授權</strong> 與控制台 Google 登入分開管理</span>
          </div>
          <div className="feature-item">
            <CheckCircle2 size={18} className="feature-icon" />
            <span>安全的 <strong>Session Cookie</strong> 加密傳輸與憑證管理</span>
          </div>
        </div>

        {/* OAuth callback and readiness errors are kept separate so a readiness refresh cannot hide a failed login. */}
          {oauthError && (
            <div className="login-error-alert">
              <AlertCircle size={18} />
              <div className="login-error-content">
              <span>{oauthError}</span>
            </div>
          </div>
        )}
        {readinessError && (
          <div className="login-error-alert">
            <AlertCircle size={18} />
            <div className="login-error-content">
              <span>{readinessError}</span>
              {!loginReady && !checkingConfig && (
                <button type="button" className="btn btn-secondary" onClick={checkLoginReadiness}>
                  <RefreshCw size={15} />重新檢查
                </button>
              )}
            </div>
          </div>
        )}

        {/* Login Action Button */}
        <div className="login-actions">
          <button 
            className="btn btn-primary login-btn"
            onClick={handleGoogleLogin}
            disabled={loggingIn || checkingConfig || !loginReady}
          >
            {checkingConfig ? (
              <>
                <span className="login-spinner"></span>
                正在檢查登入服務...
              </>
            ) : loggingIn ? (
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
          點擊登入會使用 Google OAuth 2.0 登入控制台，並授權本系統以唯讀方式讀取工作流程需要的 Google Sheet；YouTube 頻道存取權會在 YouTube 設定頁另行授權。
        </p>
      </div>
    </div>
  );
}

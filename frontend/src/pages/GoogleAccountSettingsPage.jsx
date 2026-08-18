import React from 'react';
import { CheckCircle2, ExternalLink, Key, RefreshCw, XCircle } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import { saveOAuthReturnPath } from '../utils/authReturnPath';

const GITHUB_DOCS = {
  google: 'https://github.com/minhung1126/creator-tools/blob/main/docs/GOOGLE_API_SETUP.md',
  deployment: 'https://github.com/minhung1126/creator-tools/blob/main/docs/DEPLOYMENT.md',
};

function formatTokenDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-TW');
}

function tokenStatusLabel(status) {
  return {
    active: '正常（會自動更新）',
    refresh_failed: '暫時更新失敗',
    reauthorization_required: '需要重新授權',
    not_connected: '尚未連結',
  }[status] || '未取得狀態';
}

export default function GoogleAccountSettingsPage({ authUser, sysSettings = {} }) {
  const toast = useToast();
  const location = useLocation();

  const handleStartLoginOAuth = async () => {
    try {
      saveOAuthReturnPath('google', `${location.pathname}${location.search}`);
      const result = await api.getAuthUrl();
      if (result.auth_url) window.location.href = result.auth_url;
    } catch (error) {
      toast.error(`取得控制台登入授權網址失敗：${error.message}`);
    }
  };

  return (
    <div className="settings-page-section">
      <div className="info-banner">
        <span>需要申請 API 或部署？</span>
        <a href={GITHUB_DOCS.google} target="_blank" rel="noreferrer">Google API 教學 <ExternalLink size={14} /></a>
        <a href={GITHUB_DOCS.deployment} target="_blank" rel="noreferrer">部署教學 <ExternalLink size={14} /></a>
      </div>
      <div className="glass-panel card-padding settings-card card-stack">
        <div className="card-header">
          <div className="card-header-title"><Key size={20} color="var(--primary)" /><h2>控制台登入與 Google 授權</h2></div>
          {authUser ? <span className="badge badge-connected"><CheckCircle2 size={14} /> 已連線：{authUser.email}</span> : <span className="badge badge-disconnected"><XCircle size={14} /> 未連線 Google 帳號</span>}
        </div>
        <div className="info-banner"><span>這個 Google 帳號負責登入控制台與讀取自己的工作設定；YouTube 頻道授權請至 YouTube 設定獨立管理。</span></div>
        <div className="info-banner"><span>Google Client ID 與 Client Secret 由伺服器端 `.env` 管理。{sysSettings.google_client_configured ? ' ✅ Credentials 已設定。' : ' ⚠️ Credentials 尚未設定。'}</span></div>
        {authUser && <div className="settings-grid">
          <div className="glass-panel settings-info-card"><strong>Token 狀態</strong><p>{tokenStatusLabel(authUser.token_status)}</p></div>
          <div className="glass-panel settings-info-card"><strong>最近更新</strong><p>{formatTokenDate(authUser.last_refreshed_at)}</p></div>
          <div className="glass-panel settings-info-card"><strong>目前到期時間</strong><p>{formatTokenDate(authUser.token_expires_at)}</p></div>
        </div>}
        {authUser?.last_refresh_error && <div className="info-banner"><XCircle size={16} /><span>控制台登入 Token 最近更新未成功；請重新連結控制台 Google 帳號。</span></div>}
        <p className="section-desc">控制台 Google Access Token 會在到期前 5 分鐘由後端自動更新，Refresh Token 以加密方式保存，不放在瀏覽器 Cookie 中。</p>
        {sysSettings.redirect_uri && <div className="settings-code-block"><p><strong>Google Authorized Redirect URI：</strong></p><code>{sysSettings.redirect_uri}</code></div>}
        <div className="page-actions settings-card-actions"><button className="btn btn-primary" onClick={handleStartLoginOAuth} type="button"><RefreshCw size={16} /> 重新連結控制台 Google 帳號</button></div>
      </div>
    </div>
  );
}


import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ExternalLink, FileSpreadsheet, Globe, Key, RefreshCw, Save, XCircle, Youtube } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import SourceLinkInput from '../components/SourceLinkInput';
import { readPersistentJson, writePersistentJson } from '../utils/persistentStorage';

const GITHUB_DOCS = {
  google: 'https://github.com/minhung1126/creator-tools/blob/main/docs/GOOGLE_API_SETUP.md',
  deployment: 'https://github.com/minhung1126/creator-tools/blob/main/docs/DEPLOYMENT.md',
};
const STORAGE_KEY = 'creator-tools.settings.v1';

function initialFormData(defaultSpreadsheetId) {
  const saved = readPersistentJson(STORAGE_KEY, {});
  return {
    default_spreadsheet_id: defaultSpreadsheetId ?? saved.default_spreadsheet_id ?? '',
  };
}

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

export default function SettingsPage({ authUser, sysSettings, refreshSettings }) {
  const toast = useToast();
  const [formData, setFormData] = useState(() => initialFormData(sysSettings.default_spreadsheet_id));
  const [saving, setSaving] = useState(false);
  const [youtubeConnecting, setYoutubeConnecting] = useState(false);
  const [msg, setMsg] = useState(null);
  const saveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const saveVersionRef = useRef(0);
  const dirtyRef = useRef(false);

  const youtube = authUser?.youtube || {};
  const youtubeConnected = Boolean(authUser?.youtube_authenticated || youtube.authenticated);
  const youtubeUser = youtube.user || {};

  useEffect(() => {
    if (dirtyRef.current) return;
    setFormData(initialFormData(sysSettings.default_spreadsheet_id));
  }, [sysSettings.default_spreadsheet_id]);

  const queueSave = (nextData, { notify = false } = {}) => {
    const version = saveVersionRef.current + 1;
    saveVersionRef.current = version;
    saveChainRef.current = saveChainRef.current
      .catch(() => undefined)
      .then(async () => {
        if (version !== saveVersionRef.current) return;
        setSaving(true);
        setMsg(null);
        try {
          await api.updateSharedSettings(nextData);
          if (version !== saveVersionRef.current) return;
          dirtyRef.current = false;
          await refreshSettings();
          if (version === saveVersionRef.current) {
            setMsg({ type: 'success', text: '共用 Google Sheet 設定已自動儲存。' });
            if (notify) toast.success('設定已儲存');
          }
        } catch (error) {
          if (version !== saveVersionRef.current) return;
          setMsg({ type: 'error', text: error.message || '儲存失敗；瀏覽器快取仍已保留。' });
          if (notify) toast.error(`儲存失敗：${error.message || '未知錯誤'}`);
        } finally {
          if (version === saveVersionRef.current) setSaving(false);
        }
      });
    return saveChainRef.current;
  };

  const scheduleSave = (nextData) => {
    window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      queueSave(nextData);
    }, 500);
  };

  const handleChange = (field, value) => {
    const nextData = { ...formData, [field]: value };
    dirtyRef.current = true;
    setFormData(nextData);
    writePersistentJson(STORAGE_KEY, nextData);
    scheduleSave(nextData);
  };

  const handleSave = async (event) => {
    event.preventDefault();
    window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
    await queueSave(formData, { notify: true });
  };

  useEffect(() => () => window.clearTimeout(saveTimerRef.current), []);

  const handleStartLoginOAuth = async () => {
    try {
      const result = await api.getAuthUrl();
      if (result.auth_url) window.location.href = result.auth_url;
    } catch (error) {
      toast.error(`取得控制台登入授權網址失敗：${error.message}`);
    }
  };

  const handleStartYoutubeOAuth = async () => {
    setYoutubeConnecting(true);
    try {
      const result = await api.getYoutubeAuthUrl();
      if (result.auth_url) window.location.href = result.auth_url;
    } catch (error) {
      toast.error(`取得 YouTube 頻道授權網址失敗：${error.message}`);
      setYoutubeConnecting(false);
    }
  };

  return (
    <div className="section-gap" style={{ maxWidth: 1000 }}>
      <div>
        <h1 style={{ fontSize: '1.8rem', marginBottom: 6 }}>全域與 Google 設定</h1>
        <p className="section-desc">控制台登入、共用 Google Sheet 與 YouTube 頻道授權分開管理。YouTube 播放清單請至 YouTube 設定。</p>
      </div>

      {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}
      <div className="info-banner">
        <span>需要申請 API 或部署？</span>
        <a href={GITHUB_DOCS.google} target="_blank" rel="noreferrer">Google API 教學 <ExternalLink size={14} /></a>
        <a href={GITHUB_DOCS.deployment} target="_blank" rel="noreferrer">部署教學 <ExternalLink size={14} /></a>
      </div>

      <div className="glass-panel card-padding" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="card-header">
          <div className="card-header-title"><Key size={20} color="var(--primary)" /><h3 style={{ fontSize: '1.2rem' }}>控制台登入與 Google Sheet 授權</h3></div>
          {authUser
            ? <span className="badge badge-connected"><CheckCircle2 size={14} /> 已連線：{authUser.email}</span>
            : <span className="badge badge-disconnected"><XCircle size={14} /> 未連線 Google 帳號</span>}
        </div>
        <div className="info-banner"><span>這個 Google 帳號只負責登入控制台與讀取共用 Google Sheet；YouTube 頻道在下方使用另一個獨立授權。</span></div>
        <div className="info-banner"><span>Google Client ID 與 Client Secret 由伺服器端 <code>.env</code> 管理。{sysSettings.google_client_configured ? ' ✅ Credentials 已設定。' : ' ⚠️ Credentials 尚未設定。'}</span></div>
        {authUser && <div className="form-grid-2">
          <div className="glass-panel" style={{ padding: 12 }}><strong>Token 狀態</strong><p>{tokenStatusLabel(authUser.token_status)}</p></div>
          <div className="glass-panel" style={{ padding: 12 }}><strong>最近更新</strong><p>{formatTokenDate(authUser.last_refreshed_at)}</p></div>
          <div className="glass-panel" style={{ padding: 12 }}><strong>目前到期時間</strong><p>{formatTokenDate(authUser.token_expires_at)}</p></div>
        </div>}
        {authUser?.last_refresh_error && <div className="info-banner"><XCircle size={16} /><span>控制台登入 Token 最近更新未成功；請重新連結控制台 Google 帳號。</span></div>}
        <p className="section-desc">控制台 Google Access Token 會在到期前 5 分鐘由後端自動更新，Refresh Token 以加密方式保存，不放在瀏覽器 Cookie 中。</p>
        {sysSettings.redirect_uri && <div style={{ background: 'rgba(10, 13, 20, 0.5)', padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: 4 }}><strong>Google Authorized Redirect URI：</strong></p>
          <code style={{ fontSize: '0.85rem', color: '#a5b4fc', wordBreak: 'break-all' }}>{sysSettings.redirect_uri}</code>
        </div>}
        <button className="btn btn-primary" onClick={handleStartLoginOAuth} type="button" style={{ width: 'fit-content' }}><RefreshCw size={16} /> 重新連結控制台 Google 帳號</button>
      </div>

      <div className="glass-panel card-padding" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="card-header">
          <div className="card-header-title"><Youtube size={20} color="#ff4d6d" /><h3 style={{ fontSize: '1.2rem' }}>YouTube 頻道 Google 授權</h3></div>
          {youtubeConnected
            ? <span className="badge badge-connected"><CheckCircle2 size={14} /> 已連線：{youtubeUser.email || 'YouTube 帳號'}</span>
            : <span className="badge badge-disconnected"><XCircle size={14} /> 尚未連結</span>}
        </div>
        <div className="info-banner">
          <Youtube size={18} />
          <span>這個授權與上方控制台登入完全分開。請在 Google 授權視窗選擇「管理品牌帳號的 Google 帳號」，YouTube API 將使用該帳號可管理的頻道。</span>
        </div>
        {youtubeConnected && <div className="form-grid-2">
          <div className="glass-panel" style={{ padding: 12 }}><strong>授權帳號</strong><p style={{ wordBreak: 'break-all' }}>{youtubeUser.email || '—'}</p></div>
          <div className="glass-panel" style={{ padding: 12 }}><strong>Token 狀態</strong><p>{tokenStatusLabel(youtube.token_status)}</p></div>
          <div className="glass-panel" style={{ padding: 12 }}><strong>最近更新</strong><p>{formatTokenDate(youtube.last_refreshed_at)}</p></div>
          <div className="glass-panel" style={{ padding: 12 }}><strong>目前到期時間</strong><p>{formatTokenDate(youtube.token_expires_at)}</p></div>
        </div>}
        {youtube.last_refresh_error && <div className="info-banner"><XCircle size={16} /><span>YouTube 授權 Token 最近更新未成功，請重新授權管理品牌帳號的 Google 帳號。</span></div>}
        <p className="section-desc">重新授權會替換目前保存的 YouTube 頻道連線，但不會登出控制台，也不會改變共用 Google Sheet 的登入帳號。</p>
        <button className="btn btn-primary" onClick={handleStartYoutubeOAuth} type="button" disabled={youtubeConnecting} style={{ width: 'fit-content' }}>
          {youtubeConnecting ? <><span className="login-spinner"></span> 正在傳送至 Google 授權...</> : <><ExternalLink size={16} /> {youtubeConnected ? '重新授權 YouTube 頻道' : '連結 YouTube 頻道 Google 帳號'}</>}
        </button>
      </div>

      <div className="glass-panel card-padding" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div><h3 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: 10 }}><FileSpreadsheet size={20} color="var(--accent)" /> 共用 Google Sheet</h3><p className="section-desc">這是未指定其他來源時的共用預設值，供 Sheet 內容複製與 YouTube 工作流作為 fallback 使用；修改後會自動儲存。</p></div>
        <div className="form-group"><label className="form-label"><FileSpreadsheet size={14} /> 預設 Google Sheet 網址或 Spreadsheet ID</label><SourceLinkInput value={formData.default_spreadsheet_id} onChange={(e) => handleChange('default_spreadsheet_id', e.target.value)} sourceType="spreadsheet" /><p className="section-desc">修改後會自動儲存，並同步保留於此瀏覽器作為離線快取。</p></div>
      </div>

      <div className="glass-panel card-padding"><h3 style={{ display: 'flex', alignItems: 'center', gap: 10 }}><Globe size={20} /> 系統／部署資訊（唯讀）</h3><div className="form-grid-2"><div className="form-group"><label className="form-label">對外公開網址（PUBLIC_BASE_URL）</label><input className="form-input" value={sysSettings.public_base_url || sysSettings.host || ''} readOnly /></div><div className="form-group"><label className="form-label">伺服器監聽位址（BIND_HOST）</label><input className="form-input" value={sysSettings.bind_host || ''} readOnly /></div><div className="form-group"><label className="form-label">Frontend URL</label><input className="form-input" value={sysSettings.frontend_url || ''} readOnly /></div></div><p className="section-desc">這些值由部署環境的 `.env` 管理，不屬於 Google 或 YouTube 工作流設定。BIND_HOST 控制服務監聽哪張網卡；PUBLIC_BASE_URL 是外部使用者網址，也是 Google OAuth callback 的來源。</p></div>

      <button className="btn btn-success" onClick={handleSave} disabled={saving} style={{ width: 'fit-content' }}><Save size={18} /> {saving ? '儲存中...' : '立即儲存共用設定'}</button>
    </div>
  );
}

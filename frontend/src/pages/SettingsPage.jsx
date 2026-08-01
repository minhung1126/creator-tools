import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import { Key, Globe, FileSpreadsheet, PlaySquare, CheckCircle2, XCircle, Save, ExternalLink } from 'lucide-react';

const GITHUB_DOCS = {
  google: 'https://github.com/minhung1126/creator-tools/blob/main/docs/GOOGLE_API_SETUP.md',
  deployment: 'https://github.com/minhung1126/creator-tools/blob/main/docs/DEPLOYMENT.md',
};

export default function SettingsPage({ authUser, sysSettings, refreshSettings }) {
  const toast = useToast();
  const [formData, setFormData] = useState({ default_spreadsheet_id: sysSettings.default_spreadsheet_id || '', default_playlist_id: sysSettings.default_playlist_id || '' });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  useEffect(() => { setFormData({ default_spreadsheet_id: sysSettings.default_spreadsheet_id || '', default_playlist_id: sysSettings.default_playlist_id || '' }); }, [sysSettings]);
  const handleChange = (field, value) => setFormData((current) => ({ ...current, [field]: value }));
  const handleSave = async (event) => { event.preventDefault(); setSaving(true); setMsg(null); try { await api.updateSettings(formData); await refreshSettings(); setMsg({ type: 'success', text: 'Google / YouTube 資源設定已儲存。' }); toast.success('設定已儲存'); } catch (error) { setMsg({ type: 'error', text: error.message || '儲存失敗' }); toast.error(`儲存失敗：${error.message || '未知錯誤'}`); } finally { setSaving(false); } };
  const handleStartOAuth = async () => { try { const result = await api.getAuthUrl(); if (result.auth_url) window.location.href = result.auth_url; } catch (error) { toast.error(`取得授權網址失敗：${error.message}`); } };
  return <div className="section-gap" style={{ maxWidth: 1000 }}>
    <div><h1 style={{ fontSize: '1.8rem', marginBottom: 6 }}>Google / YouTube 設定</h1><p className="section-desc">管理 Google OAuth、Sheets、Drive 與 YouTube。Instagram 與 R2 已移至獨立平台設定頁。</p></div>
    {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}
    <div className="info-banner"><span>需要申請 API 或部署？</span><a href={GITHUB_DOCS.google} target="_blank" rel="noreferrer">Google API 教學 <ExternalLink size={14} /></a><a href={GITHUB_DOCS.deployment} target="_blank" rel="noreferrer">部署教學 <ExternalLink size={14} /></a></div>
    <div className="glass-panel card-padding" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}><div className="card-header"><div className="card-header-title"><Key size={20} color="var(--primary)" /><h3 style={{ fontSize: '1.2rem' }}>Google OAuth 2.0 帳號授權管理</h3></div>{authUser ? <span className="badge badge-connected"><CheckCircle2 size={14} /> 已連線：{authUser.email}</span> : <span className="badge badge-disconnected"><XCircle size={14} /> 未連線 Google 帳號</span>}</div><div className="info-banner"><span>Google Client ID 與 Client Secret 由伺服器端 <code>.env</code> 管理。{sysSettings.google_client_configured ? ' ✅ Credentials 已設定。' : ' ⚠️ Credentials 尚未設定。'}</span></div>{sysSettings.redirect_uri && <div style={{ background: 'rgba(10, 13, 20, 0.5)', padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}><p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: 4 }}><strong>Google Authorized Redirect URI：</strong></p><code style={{ fontSize: '0.85rem', color: '#a5b4fc', wordBreak: 'break-all' }}>{sysSettings.redirect_uri}</code></div>}<button className="btn btn-primary" onClick={handleStartOAuth} type="button" style={{ width: 'fit-content' }}><ExternalLink size={16} /> {authUser ? '重新連結 Google 帳號' : '開始 Google 帳號授權連線'}</button></div>
    <div className="glass-panel card-padding" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}><div><h3 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: 10 }}><FileSpreadsheet size={20} color="var(--accent)" /> Google / YouTube 預設資源</h3><p className="section-desc">以下資源只由網頁設定並保存到伺服器的 data/runtime_config.json，不再從 .env 帶入。</p></div><div className="form-group"><label className="form-label"><FileSpreadsheet size={14} /> 預設 Google Sheet 網址或 Spreadsheet ID</label><input className="form-input" value={formData.default_spreadsheet_id} onChange={(e) => handleChange('default_spreadsheet_id', e.target.value)} /></div><div className="form-group"><label className="form-label"><PlaySquare size={14} /> 預設 YouTube To-Post 播放清單 ID</label><input className="form-input" value={formData.default_playlist_id} onChange={(e) => handleChange('default_playlist_id', e.target.value)} /></div></div>
    <div className="glass-panel card-padding"><h3 style={{ display: 'flex', alignItems: 'center', gap: 10 }}><Globe size={20} /> 網路設定資訊</h3><div className="form-grid-2"><div className="form-group"><label className="form-label">對外公開網址（PUBLIC_BASE_URL）</label><input className="form-input" value={sysSettings.public_base_url || sysSettings.host || ''} readOnly /></div><div className="form-group"><label className="form-label">伺服器監聽位址（BIND_HOST）</label><input className="form-input" value={sysSettings.bind_host || ''} readOnly /></div><div className="form-group"><label className="form-label">Frontend URL</label><input className="form-input" value={sysSettings.frontend_url || ''} readOnly /></div></div><p className="section-desc">BIND_HOST 控制服務監聽哪張網卡；PUBLIC_BASE_URL 是外部使用者網址，也是 OAuth callback 的來源。</p></div>
    <button className="btn btn-success" onClick={handleSave} disabled={saving} style={{ width: 'fit-content' }}><Save size={18} /> {saving ? '儲存中...' : '儲存 Google / YouTube 設定'}</button>
  </div>;
}

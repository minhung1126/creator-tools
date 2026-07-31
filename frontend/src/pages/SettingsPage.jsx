import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { 
  Key, 
  Globe, 
  FileSpreadsheet, 
  Folder, 
  PlaySquare, 
  CheckCircle2, 
  XCircle, 
  Save, 
  Share2, 
  Lock,
  ExternalLink
} from 'lucide-react';

export default function SettingsPage({ authUser, sysSettings, refreshSettings, refreshUser }) {
  const [formData, setFormData] = useState({
    host: sysSettings.host || 'http://localhost:8000',
    frontend_url: sysSettings.frontend_url || 'http://localhost:3000',
    google_client_id: sysSettings.google_client_id || '',
    google_client_secret: '',
    default_spreadsheet_id: sysSettings.default_spreadsheet_id || '',
    default_playlist_id: sysSettings.default_playlist_id || '',
    default_drive_folder_id: sysSettings.default_drive_folder_id || '',
    meta_app_id: sysSettings.meta_app_id || '',
    meta_app_secret: '',
    meta_access_token: ''
  });

  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    setFormData((prev) => ({
      ...prev,
      host: sysSettings.host || 'http://localhost:8000',
      frontend_url: sysSettings.frontend_url || 'http://localhost:3000',
      google_client_id: sysSettings.google_client_id || '',
      default_spreadsheet_id: sysSettings.default_spreadsheet_id || '',
      default_playlist_id: sysSettings.default_playlist_id || '',
      default_drive_folder_id: sysSettings.default_drive_folder_id || '',
      meta_app_id: sysSettings.meta_app_id || ''
    }));
  }, [sysSettings]);

  const handleChange = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      await api.updateSettings(formData);
      await refreshSettings();
      setMsg({ type: 'success', text: '系統設定與資源設定更新成功！' });
    } catch (err) {
      setMsg({ type: 'error', text: err.message || '儲存失敗' });
    } finally {
      setSaving(false);
    }
  };

  const handleStartOAuth = async () => {
    try {
      const res = await api.getAuthUrl(formData.google_client_id, formData.google_client_secret);
      if (res.auth_url) {
        window.location.href = res.auth_url;
      }
    } catch (err) {
      alert(`取得授權網址失敗：${err.message}`);
    }
  };

  const redirectUri = sysSettings.redirect_uri || `${formData.host.replace(/\/$/, '')}/api/v1/auth/callback`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px', maxWidth: '1000px' }}>
      <div>
        <h1 style={{ fontSize: '1.8rem', marginBottom: '6px' }}>系統與帳號設定</h1>
        <p style={{ color: 'var(--text-muted)' }}>
          統一管理 Google OAuth 認證、Host 網址、Google Sheets / Drive / YouTube 資源 ID，以及未來 Meta API 的擴充設定。
        </p>
      </div>

      {msg && (
        <div style={{
          padding: '14px 18px',
          borderRadius: 'var(--radius-md)',
          background: msg.type === 'success' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
          border: `1px solid ${msg.type === 'success' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
          color: msg.type === 'success' ? '#34d399' : '#f87171',
          fontSize: '0.9rem',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          {msg.type === 'success' ? <CheckCircle2 size={18}/> : <XCircle size={18}/>}
          {msg.text}
        </div>
      )}

      {/* Card 1: Google OAuth 2.0 Management */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Key size={20} color="var(--primary)" />
            <h3 style={{ fontSize: '1.2rem' }}>Google OAuth 2.0 帳號授權管理</h3>
          </div>
          {authUser ? (
            <span className="badge badge-connected"><CheckCircle2 size={14}/> 已連線：{authUser.email}</span>
          ) : (
            <span className="badge badge-disconnected"><XCircle size={14}/> 未連線 Google 帳號</span>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div className="form-group">
            <label className="form-label"><Lock size={14}/> Google Client ID</label>
            <input 
              className="form-input" 
              type="text" 
              placeholder="e.g. 123456789-abc.apps.googleusercontent.com"
              value={formData.google_client_id}
              onChange={(e) => handleChange('google_client_id', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label"><Lock size={14}/> Google Client Secret</label>
            <input 
              className="form-input" 
              type="password" 
              placeholder={sysSettings.google_client_secret_set ? "•••••••••••• (已設定，若不修改請留空)" : "輸入 Client Secret"}
              value={formData.google_client_secret}
              onChange={(e) => handleChange('google_client_secret', e.target.value)}
            />
          </div>
        </div>

        <div style={{ background: 'rgba(10, 13, 20, 0.5)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            <strong>Authorized Redirect URI (請填入 Google Cloud Console):</strong>
          </p>
          <code style={{ fontSize: '0.85rem', color: '#a5b4fc', wordBreak: 'break-all' }}>
            {redirectUri}
          </code>
        </div>

        <div style={{ display: 'flex', gap: '12px' }}>
          <button className="btn btn-primary" onClick={handleStartOAuth} type="button">
            <ExternalLink size={16} /> {authUser ? '重新連結 Google 帳號' : '開始 Google 帳號授權連線'}
          </button>
        </div>
      </div>

      {/* Card 2: Unified Resource Management (Sheets, Drive, YouTube) */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '14px' }}>
          <h3 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileSpreadsheet size={20} color="var(--accent)" /> 統一資源網址與 ID 設定 (Sheets / Drive / YouTube)
          </h3>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            在這裡設定預設的 Google Sheet 對照表網址、Google Drive 資料夾以及 YouTube 播放清單，系統會自動在功能頁面中預載使用。
          </p>
        </div>

        <div className="form-group">
          <label className="form-label"><FileSpreadsheet size={14}/> 預設 Google Sheet 網址或 Spreadsheet ID</label>
          <input 
            className="form-input" 
            type="text" 
            placeholder="e.g. https://docs.google.com/spreadsheets/d/1xsxDJ80-TOQs3d3ecHALEbyMlxxEkwXNjHaW7yA8wVs/edit"
            value={formData.default_spreadsheet_id}
            onChange={(e) => handleChange('default_spreadsheet_id', e.target.value)}
          />
          <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>
            必須包含工作表「Youtube Video」與「Youtube Shorts」，且欄位包含：所屬團體、人、Youtube Title、Youtube Description。
          </span>
        </div>

        <div className="form-group">
          <label className="form-label"><PlaySquare size={14}/> 預設 YouTube To-Post 播放清單 ID</label>
          <input 
            className="form-input" 
            type="text" 
            placeholder="e.g. PLhu1MP3FpZmHar5qPZJkl6zCqXzddF4nC"
            value={formData.default_playlist_id}
            onChange={(e) => handleChange('default_playlist_id', e.target.value)}
          />
        </div>

        <div className="form-group">
          <label className="form-label"><Folder size={14}/> 預設 Google Drive 資料夾網址或 ID (選填)</label>
          <input 
            className="form-input" 
            type="text" 
            placeholder="e.g. https://drive.google.com/drive/folders/..."
            value={formData.default_drive_folder_id}
            onChange={(e) => handleChange('default_drive_folder_id', e.target.value)}
          />
        </div>
      </div>

      {/* Card 3: Host Configuration */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '14px' }}>
          <h3 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Globe size={20} color="var(--secondary)" /> Host 伺服器網址設定
          </h3>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            設定此系統運行的 HOST 網址，以供 OAuth 重導向（API Redirect URI）與 API Gateway 組合使用。
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div className="form-group">
            <label className="form-label">Backend HOST URL</label>
            <input 
              className="form-input" 
              type="text" 
              value={formData.host}
              onChange={(e) => handleChange('host', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Frontend App URL</label>
            <input 
              className="form-input" 
              type="text" 
              value={formData.frontend_url}
              onChange={(e) => handleChange('frontend_url', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Card 4: Meta API Integration Slot (Extensibility Requirement) */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h3 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Share2 size={20} color="#3b82f6" /> Meta API 功能擴充設定 (Facebook / Instagram)
            </h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              預留未來 Meta (Facebook / Instagram) 自動化社群同步功能之擴充介面與 API 金鑰設定。
            </p>
          </div>
          <span className="badge badge-info">擴充預留</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div className="form-group">
            <label className="form-label">Meta App ID</label>
            <input 
              className="form-input" 
              type="text" 
              placeholder="Meta App ID"
              value={formData.meta_app_id}
              onChange={(e) => handleChange('meta_app_id', e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Meta App Secret</label>
            <input 
              className="form-input" 
              type="password" 
              placeholder="Meta App Secret"
              value={formData.meta_app_secret}
              onChange={(e) => handleChange('meta_app_secret', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div>
        <button 
          className="btn btn-success" 
          onClick={handleSave} 
          disabled={saving}
          style={{ padding: '12px 28px', fontSize: '1rem' }}
        >
          <Save size={18} /> {saving ? '儲存中...' : '儲存所有系統設定'}
        </button>
      </div>
    </div>
  );
}

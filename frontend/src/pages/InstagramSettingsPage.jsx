import React, { useEffect, useState } from 'react';
import { CheckCircle2, ExternalLink, Link2, RefreshCw, Save, TestTube2, Unlink, XCircle } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';

function formatDate(value) {
  if (!value) return '未提供';
  try {
    return new Intl.DateTimeFormat('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
  } catch { return value; }
}

export default function InstagramSettingsPage({ refreshKey = 0 }) {
  const toast = useToast();
  const [form, setForm] = useState({});
  const [savedForm, setSavedForm] = useState({});
  const [authStatus, setAuthStatus] = useState({ connected: false, account: null });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingR2, setTestingR2] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [confirmR2Save, setConfirmR2Save] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [settings, status] = await Promise.all([api.getInstagramSettings(), api.getInstagramAuthStatus()]);
      setForm(settings || {});
      setSavedForm(settings || {});
      setAuthStatus(status || { connected: false, account: null });
    } catch (error) { toast.error(error.message); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [refreshKey]);

  const connect = async () => {
    try { const result = await api.getInstagramAuthUrl(); window.location.assign(result.auth_url); }
    catch (error) { toast.error(error.message); }
  };
  const refreshToken = async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshInstagramAuth();
      setAuthStatus((current) => ({ ...current, connected: true, account: result.account }));
      toast.success('Instagram Token 與帳號資料已更新');
    } catch (error) { toast.error(error.message); } finally { setRefreshing(false); }
  };
  const disconnect = async () => {
    setConfirmDisconnect(false);
    try {
      await api.disconnectInstagram();
      setAuthStatus((current) => ({ ...current, connected: false, account: null }));
      toast.success('Instagram 連線已移除');
    } catch (error) { toast.error(error.message); }
  };
  const save = async () => {
    setSaving(true);
    try {
      const result = await api.updateInstagramSettings(form);
      setForm((current) => ({ ...current, ...result, r2_secret_access_key: '' }));
      setSavedForm((current) => ({ ...current, ...result, r2_secret_access_key: '' }));
      toast.success('Instagram 工作流程與 R2 設定已儲存');
      return true;
    } catch (error) { toast.error(error.message); return false; } finally { setSaving(false); }
  };
  const runR2Test = async () => {
    setTestingR2(true);
    try { const result = await api.testInstagramR2(); toast.success(`R2 連線成功：${result.bucket_name}`); }
    catch (error) { toast.error(error.message); } finally { setTestingR2(false); }
  };
  const testR2 = () => {
    const current = { ...form, r2_secret_access_key: form.r2_secret_access_key || '' };
    const saved = { ...savedForm, r2_secret_access_key: savedForm.r2_secret_access_key || '' };
    if (JSON.stringify(current) !== JSON.stringify(saved)) {
      setConfirmR2Save(true);
      return;
    }
    runR2Test();
  };
  const saveAndTestR2 = async () => {
    setConfirmR2Save(false);
    if (await save()) runR2Test();
  };

  const account = authStatus.account;
  const connected = authStatus.connected && account;
  if (loading) return <div className="loading-center">讀取 Instagram 設定中...</div>;

  return <div className="section-gap" style={{ maxWidth: 980 }}>
    <div><h1>Instagram / R2 設定</h1><p className="section-desc">Instagram 帳號透過官方登入流程授權；帳號 ID 與 Access Token 由後端自動取得並加密儲存。</p></div>

    <section className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}><div><h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{connected ? <CheckCircle2 size={20} /> : <XCircle size={20} />}Instagram 帳號</h2><p className="section-desc">{connected ? `已連線 @${account.username || 'Instagram account'}` : '尚未完成 Instagram Login 授權'}</p></div><span className={`badge ${connected ? 'badge-connected' : 'badge-disconnected'}`}>{connected ? '已連線' : '未連線'}</span></div>
      {!authStatus.app_configured && <div className="info-banner"><XCircle size={16} /><span>伺服器尚未設定 INSTAGRAM_APP_ID 與 INSTAGRAM_APP_SECRET。</span></div>}
      {connected ? <div style={{ display: 'grid', gap: 10 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 10 }}><div className="glass-panel" style={{ padding: 12 }}><strong>帳號</strong><p>@{account.username || '—'}</p></div><div className="glass-panel" style={{ padding: 12 }}><strong>帳號類型</strong><p>{account.account_type || '—'}</p></div><div className="glass-panel" style={{ padding: 12 }}><strong>Instagram User ID</strong><p style={{ wordBreak: 'break-all' }}>{account.instagram_user_id}</p></div><div className="glass-panel" style={{ padding: 12 }}><strong>Token 到期</strong><p>{formatDate(account.token_expires_at)}</p></div></div>
        <div><strong>已授權權限</strong><p className="section-desc">{account.permissions_verified && (account.granted_scopes || []).length ? account.granted_scopes.join('、') : '未提供／尚未驗證'}</p></div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}><button className="btn btn-primary" onClick={connect}><Link2 size={17} />重新授權／切換帳號</button><button className="btn btn-secondary" onClick={refreshToken} disabled={refreshing}><RefreshCw size={17} />{refreshing ? '更新中…' : '更新 Token'}</button><button className="btn btn-danger" onClick={() => setConfirmDisconnect(true)}><Unlink size={17} />中斷連線</button></div>
      </div> : <div style={{ display: 'grid', gap: 12 }}><p>按下按鈕後會前往 Instagram 登入與授權頁；完成後會自動取得帳號 ID、帳號名稱與 Token。</p><button className="btn btn-primary" onClick={connect} disabled={!authStatus.app_configured} style={{ width: 'fit-content' }}><ExternalLink size={17} />使用 Instagram 登入並授權</button></div>}
      <div className="info-banner"><CheckCircle2 size={16} /><span>Meta 後台 Valid OAuth Redirect URI 必須完全等於：<code>{authStatus.redirect_uri}</code></span></div>
    </section>

    <section className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}><div><h2>Instagram 工作流程預設值</h2><p className="section-desc">預先帶入 Reels 自動發布頁。</p></div><label className="form-group"><span className="form-label">Google Drive 資料夾 ID／網址</span><input className="form-input" value={form.drive_folder_id || ''} onChange={(e) => setForm({ ...form, drive_folder_id: e.target.value })} /></label><label className="form-group"><span className="form-label">Google Sheet ID／網址</span><input className="form-input" value={form.spreadsheet_id || ''} onChange={(e) => setForm({ ...form, spreadsheet_id: e.target.value })} /></label><p className="section-desc">Instagram API 版本由後端 release 固定，不由 UI 修改。</p></section>

    <section className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}><div><h2>Cloudflare R2</h2><p className="section-desc">R2 Secret Access Key 會加密儲存，不會由 API 回傳。</p></div><label className="form-group"><span className="form-label">R2 Account ID</span><input className="form-input" value={form.r2_account_id || ''} onChange={(e) => setForm({ ...form, r2_account_id: e.target.value })} /></label><label className="form-group"><span className="form-label">R2 Access Key ID</span><input className="form-input" value={form.r2_access_key_id || ''} onChange={(e) => setForm({ ...form, r2_access_key_id: e.target.value })} /></label><label className="form-group"><span className="form-label">R2 Secret Access Key</span><input className="form-input" type="password" value={form.r2_secret_access_key || ''} placeholder={form.r2_secret_access_key_configured ? '已設定；留空保留原值' : ''} onChange={(e) => setForm({ ...form, r2_secret_access_key: e.target.value })} /></label><label className="form-group"><span className="form-label">R2 Bucket 名稱</span><input className="form-input" value={form.r2_bucket_name || ''} onChange={(e) => setForm({ ...form, r2_bucket_name: e.target.value })} /></label><label className="form-group"><span className="form-label">R2 公開網址／Custom Domain</span><input className="form-input" value={form.r2_public_base_url || ''} onChange={(e) => setForm({ ...form, r2_public_base_url: e.target.value })} /></label><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}><button className="btn btn-success" onClick={save} disabled={saving}><Save size={17} />{saving ? '儲存中…' : '儲存設定'}</button><button className="btn btn-primary" onClick={testR2} disabled={testingR2}><TestTube2 size={17} />{testingR2 ? '測試中…' : '測試 R2'}</button></div></section>
    <div className="info-banner"><CheckCircle2 size={16} />完整申請與登入流程請看 docs/INSTAGRAM_R2_SETUP.md。</div>
    <ConfirmDialog open={confirmDisconnect} title="中斷 Instagram 連線" message="確定要刪除目前儲存的 Instagram Token？" confirmText="中斷連線" variant="destructive" onConfirm={disconnect} onCancel={() => setConfirmDisconnect(false)} />
    <ConfirmDialog open={confirmR2Save} title="先儲存 R2 修改？" message="目前表單有尚未儲存的 R2 設定。測試前先儲存這些修改，確定繼續？" confirmText="儲存並測試" onConfirm={saveAndTestR2} onCancel={() => setConfirmR2Save(false)} />
  </div>;
}

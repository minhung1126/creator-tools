import React, { useEffect, useState } from 'react';
import { CheckCircle2, Save, TestTube2 } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';

const FIELDS = [
  ['drive_folder_id', 'Google Drive 資料夾 ID／網址'],
  ['spreadsheet_id', 'Google Sheet ID／網址'],
  ['instagram_user_id', 'Instagram User ID'],
  ['instagram_access_token', 'Instagram Access Token', 'password'],
  ['instagram_api_version', 'Instagram API 版本'],
  ['r2_account_id', 'R2 Account ID'],
  ['r2_access_key_id', 'R2 Access Key ID'],
  ['r2_secret_access_key', 'R2 Secret Access Key', 'password'],
  ['r2_bucket_name', 'R2 Bucket 名稱'],
  ['r2_public_base_url', 'R2 公開網址／Custom Domain'],
];

export default function InstagramSettingsPage() {
  const toast = useToast();
  const [form, setForm] = useState({ instagram_api_version: 'v25.0' });
  const [testing, setTesting] = useState(false);

  useEffect(() => { api.getInstagramSettings().then(setForm).catch((error) => toast.error(error.message)); }, []);

  const save = async () => {
    try {
      const result = await api.updateInstagramSettings(form);
      setForm((old) => ({ ...old, ...result, instagram_access_token: '', r2_secret_access_key: '' }));
      toast.success('Instagram / R2 設定已儲存');
    } catch (error) { toast.error(error.message); }
  };

  const test = async () => {
    setTesting(true);
    try {
      const result = await api.getInstagramConnectionStatus();
      result.ok ? toast.success(`連線成功：@${result.profile?.username || ''}`) : toast.error(result.errors.join('；'));
    } catch (error) { toast.error(error.message); } finally { setTesting(false); }
  };

  return <div className="section-gap" style={{ maxWidth: 900 }}>
    <div><h1>Instagram / R2 設定</h1><p className="section-desc">Instagram Login 與 Cloudflare R2 使用獨立設定頁；空白密鑰不會覆蓋已儲存內容。</p></div>
    <div className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
      {FIELDS.map(([key, label, type = 'text']) => <label className="form-group" key={key}><span className="form-label">{label}</span><input className="form-input" type={type} value={form[key] || ''} placeholder={form[`${key}_configured`] ? '已設定；留空保留原值' : ''} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>)}
      <div style={{ display: 'flex', gap: 12 }}><button className="btn btn-success" onClick={save}><Save size={17} />儲存</button><button className="btn btn-primary" onClick={test} disabled={testing}><TestTube2 size={17} />{testing ? '測試中…' : '測試連線'}</button></div>
    </div>
    <div className="info-banner"><CheckCircle2 size={16} />完整申請流程請看 docs/INSTAGRAM_R2_SETUP.md。</div>
  </div>;
}

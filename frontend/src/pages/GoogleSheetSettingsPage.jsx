import React, { useEffect, useRef, useState } from 'react';
import { FileSpreadsheet, Save, XCircle, CheckCircle2 } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import SourceLinkInput from '../components/SourceLinkInput';

export function initialGoogleSheetForm(defaultSpreadsheetId) {
  return { default_spreadsheet_id: defaultSpreadsheetId || '' };
}

export default function GoogleSheetSettingsPage({ sysSettings = {}, refreshSettings }) {
  const toast = useToast();
  const [formData, setFormData] = useState(() => initialGoogleSheetForm(sysSettings.default_spreadsheet_id));
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const saveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const saveVersionRef = useRef(0);
  const dirtyRef = useRef(false);

  useEffect(() => {
    if (!dirtyRef.current) setFormData(initialGoogleSheetForm(sysSettings.default_spreadsheet_id));
  }, [sysSettings.default_spreadsheet_id]);

  const queueSave = (nextData, { notify = false } = {}) => {
    const version = saveVersionRef.current + 1;
    saveVersionRef.current = version;
    saveChainRef.current = saveChainRef.current.catch(() => undefined).then(async () => {
      if (version !== saveVersionRef.current) return;
      setSaving(true);
      setMsg(null);
      try {
        await api.updateSharedSettings(nextData);
        if (version !== saveVersionRef.current) return;
        dirtyRef.current = false;
        await refreshSettings?.();
        if (version === saveVersionRef.current) {
          setMsg({ type: 'success', text: '目前帳號的 Google Sheet 設定已自動儲存。' });
          if (notify) toast.success('設定已儲存');
        }
      } catch (error) {
        if (version !== saveVersionRef.current) return;
        setMsg({ type: 'error', text: error.message || '伺服器儲存失敗，請稍後重試。' });
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

  const handleChange = (value) => {
    const nextData = { ...formData, default_spreadsheet_id: value };
    dirtyRef.current = true;
    setFormData(nextData);
    scheduleSave(nextData);
  };

  const handleSave = async (event) => {
    event.preventDefault();
    window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
    await queueSave(formData, { notify: true });
  };

  useEffect(() => () => window.clearTimeout(saveTimerRef.current), []);

  return (
    <div className="settings-page-section">
      {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}
      <form className="glass-panel card-padding settings-card card-stack" onSubmit={handleSave}>
        <div><h2 className="settings-heading"><FileSpreadsheet size={20} color="var(--accent)" /> 帳號預設 Google Sheet</h2><p className="section-desc">這是目前帳號未指定其他來源時的預設值，供 Sheet 內容複製與 YouTube 工作流使用；修改後會自動儲存。</p></div>
        <div className="form-group"><label className="form-label"><FileSpreadsheet size={14} /> 預設 Google Sheet 網址或 Spreadsheet ID</label><SourceLinkInput value={formData.default_spreadsheet_id} onChange={(event) => handleChange(event.target.value)} sourceType="spreadsheet" /><p className="section-desc">修改後會自動儲存至目前登入的 Google 帳號；換瀏覽器或重新登入仍可取回。</p></div>
        <div className="page-actions settings-page-actions"><button className="btn btn-success" type="submit" disabled={saving}><Save size={18} /> {saving ? '儲存中...' : '立即儲存帳號設定'}</button></div>
      </form>
    </div>
  );
}


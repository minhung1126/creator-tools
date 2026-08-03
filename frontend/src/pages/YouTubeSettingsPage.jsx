import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, Clapperboard, PlaySquare, Save, Smartphone, XCircle } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import SourceLinkInput from '../components/SourceLinkInput';
import { readPersistentJson, writePersistentJson } from '../utils/persistentStorage';

const STORAGE_KEY = 'creator-tools.youtube-settings.v1';

function initialSettings(defaultPlaylistId, quotaLimit, quotaBuffer) {
  const saved = readPersistentJson(STORAGE_KEY, {});
  return {
    playlistId: defaultPlaylistId ?? saved.playlistId ?? '',
    quotaLimit: quotaLimit ?? saved.quotaLimit ?? 10000,
    quotaBuffer: quotaBuffer ?? saved.quotaBuffer ?? 1000,
  };
}

function toPayload(data) {
  const limit = Number(data.quotaLimit);
  const buffer = Number(data.quotaBuffer);
  if (!Number.isInteger(limit) || limit <= 0) return null;
  if (!Number.isInteger(buffer) || buffer < 0 || buffer >= limit) return null;
  return {
    default_playlist_id: String(data.playlistId || '').trim(),
    youtube_general_quota_limit: limit,
    youtube_quota_safety_buffer_units: buffer,
  };
}

export default function YouTubeSettingsPage({ sysSettings, refreshSettings, setActiveTab }) {
  const toast = useToast();
  const initial = initialSettings(sysSettings.default_playlist_id, sysSettings.youtube_general_quota_limit, sysSettings.youtube_quota_safety_buffer_units);
  const [playlistId, setPlaylistId] = useState(initial.playlistId);
  const [quotaLimit, setQuotaLimit] = useState(initial.quotaLimit);
  const [quotaBuffer, setQuotaBuffer] = useState(initial.quotaBuffer);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const saveTimerRef = useRef(null);
  const saveChainRef = useRef(Promise.resolve());
  const saveVersionRef = useRef(0);
  const dirtyRef = useRef(false);

  useEffect(() => {
    if (dirtyRef.current) return;
    const next = initialSettings(sysSettings.default_playlist_id, sysSettings.youtube_general_quota_limit, sysSettings.youtube_quota_safety_buffer_units);
    setPlaylistId(next.playlistId);
    setQuotaLimit(next.quotaLimit);
    setQuotaBuffer(next.quotaBuffer);
  }, [sysSettings.default_playlist_id, sysSettings.youtube_general_quota_limit, sysSettings.youtube_quota_safety_buffer_units]);

  const queueSave = (nextData, { notify = false } = {}) => {
    const version = saveVersionRef.current + 1;
    saveVersionRef.current = version;
    const payload = toPayload(nextData);
    if (!payload) return Promise.resolve(false);
    saveChainRef.current = saveChainRef.current
      .catch(() => undefined)
      .then(async () => {
        if (version !== saveVersionRef.current) return false;
        setSaving(true);
        setMsg(null);
        try {
          await api.updateYoutubeSettings(payload);
          if (version !== saveVersionRef.current) return false;
          dirtyRef.current = false;
          await refreshSettings();
          if (version === saveVersionRef.current) {
            setMsg({ type: 'success', text: 'YouTube 設定已自動儲存。' });
            if (notify) toast.success('YouTube 設定已儲存');
          }
          return true;
        } catch (error) {
          if (version !== saveVersionRef.current) return false;
          setMsg({ type: 'error', text: error.message || '儲存失敗；瀏覽器快取仍已保留。' });
          if (notify) toast.error(`儲存失敗：${error.message || '未知錯誤'}`);
          return false;
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
    const nextData = { playlistId, quotaLimit, quotaBuffer, [field]: value };
    dirtyRef.current = true;
    if (field === 'playlistId') setPlaylistId(value);
    if (field === 'quotaLimit') setQuotaLimit(value);
    if (field === 'quotaBuffer') setQuotaBuffer(value);
    writePersistentJson(STORAGE_KEY, nextData);
    scheduleSave(nextData);
  };

  const handleSave = async (event) => {
    event.preventDefault();
    const nextData = { playlistId, quotaLimit, quotaBuffer };
    const payload = toPayload(nextData);
    if (!payload) {
      saveVersionRef.current += 1;
      const limit = Number(quotaLimit);
      const buffer = Number(quotaBuffer);
      const message = !Number.isInteger(limit) || limit <= 0
        ? 'project quota 必須是大於 0 的整數'
        : (!Number.isInteger(buffer) || buffer < 0 || buffer >= limit
          ? '安全保留必須大於等於 0 且小於 project quota'
          : '設定格式不正確');
      setMsg({ type: 'error', text: message });
      toast.error(`儲存失敗：${message}`);
      return;
    }
    window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
    await queueSave(nextData, { notify: true });
  };

  useEffect(() => () => window.clearTimeout(saveTimerRef.current), []);

  return (
    <div className="section-gap" style={{ maxWidth: 1000 }}>
      <div>
        <h1 style={{ fontSize: '1.8rem', marginBottom: 6 }}>YouTube 設定</h1>
        <p className="section-desc">管理 YouTube 發布流程的預設資源；YouTube 頻道 Google 授權與共用 Sheet 請至「全域與 Google 設定」，兩者可使用不同 Google 帳號。</p>
      </div>

      {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}

      <form className="glass-panel card-padding" onSubmit={handleSave} style={{ display: 'grid', gap: 20 }}>
        <div>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '1.2rem' }}><PlaySquare size={20} color="var(--secondary)" /> YouTube 發布預設資源</h2>
          <p className="section-desc">這個播放清單是 YouTube 發布與清理流程的 fallback。Video／Shorts 草稿頁若保存了自己的播放清單，會優先使用工作流設定；欄位修改後會自動儲存。</p>
        </div>
        <div className="form-group">
          <label className="form-label"><PlaySquare size={14} /> 預設 To-Post 播放清單 ID</label>
          <SourceLinkInput value={playlistId} onChange={(event) => handleChange('playlistId', event.target.value)} sourceType="youtube-playlist" placeholder="YouTube Playlist ID" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
          <div className="form-group">
            <label className="form-label">Google Cloud project 一般 YouTube quota</label>
            <input className="form-input" type="number" min="1" step="1" value={quotaLimit} onChange={(event) => handleChange('quotaLimit', event.target.value)} />
            <p className="section-desc">請依 Google Cloud Console 的一般 YouTube Data API bucket 填寫。官方預設值為 10,000。</p>
          </div>
          <div className="form-group">
            <label className="form-label">Creator Tools 安全保留 units</label>
            <input className="form-input" type="number" min="0" step="1" value={quotaBuffer} onChange={(event) => handleChange('quotaBuffer', event.target.value)} />
            <p className="section-desc">Creator Tools 自訂安全保留，非 YouTube 官方限制；必須小於 project quota。</p>
          </div>
        </div>
        <button className="btn btn-success" type="submit" disabled={saving} style={{ width: 'fit-content' }}><Save size={18} />{saving ? '儲存中...' : '立即儲存 YouTube 設定'}</button>
      </form>

      <section className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
        <div>
          <h2 style={{ fontSize: '1.2rem' }}>YouTube 草稿工作流設定</h2>
          <p className="section-desc">Video 與 Shorts 的工作表、欄位、團體、人物篩選與工作流資源，會在各自功能頁編輯並自動保存。</p>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 12 }}>
          <div className="glass-panel" style={{ padding: 16, display: 'grid', gap: 10 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1rem' }}><Clapperboard size={18} /> Video 草稿</h3>
            <p className="section-desc">管理 Video 專屬工作表、欄位與人物選項。</p>
            <button className="btn btn-secondary" type="button" onClick={() => setActiveTab('youtube_video_drafts')} style={{ width: 'fit-content' }}>前往 Video 設定 <ArrowRight size={16} /></button>
          </div>
          <div className="glass-panel" style={{ padding: 16, display: 'grid', gap: 10 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1rem' }}><Smartphone size={18} /> Shorts 草稿</h3>
            <p className="section-desc">管理 Shorts 專屬工作表、欄位與人物選項。</p>
            <button className="btn btn-secondary" type="button" onClick={() => setActiveTab('youtube_shorts_drafts')} style={{ width: 'fit-content' }}>前往 Shorts 設定 <ArrowRight size={16} /></button>
          </div>
        </div>
      </section>
    </div>
  );
}

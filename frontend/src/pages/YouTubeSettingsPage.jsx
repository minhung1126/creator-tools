import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, Clapperboard, ExternalLink, PlaySquare, Save, Smartphone, XCircle, Youtube } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import SourceLinkInput from '../components/SourceLinkInput';
import { readPersistentJson, resolvePersistentValue, writePersistentJson } from '../utils/persistentStorage';

const STORAGE_KEY = 'creator-tools.youtube-settings.v1';

export function initialSettings(defaultPlaylistId, quotaLimit, quotaBuffer) {
  const saved = readPersistentJson(STORAGE_KEY, {});
  return {
    playlistId: resolvePersistentValue(saved, 'playlistId', defaultPlaylistId, ''),
    quotaLimit: resolvePersistentValue(saved, 'quotaLimit', quotaLimit, 10000),
    quotaBuffer: resolvePersistentValue(saved, 'quotaBuffer', quotaBuffer, 1000),
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

export default function YouTubeSettingsPage({ authUser, sysSettings, refreshSettings, setActiveTab }) {
  const toast = useToast();
  const initial = initialSettings(sysSettings.default_playlist_id, sysSettings.youtube_general_quota_limit, sysSettings.youtube_quota_safety_buffer_units);
  const [playlistId, setPlaylistId] = useState(initial.playlistId);
  const [quotaLimit, setQuotaLimit] = useState(initial.quotaLimit);
  const [quotaBuffer, setQuotaBuffer] = useState(initial.quotaBuffer);
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
          writePersistentJson(STORAGE_KEY, { ...nextData, _pending: false });
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
    writePersistentJson(STORAGE_KEY, { ...nextData, _pending: true });
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

  useEffect(() => () => window.clearTimeout(saveTimerRef.current), []);

  return (
    <div className="section-gap settings-page youtube-settings-page">
      <header className="page-header">
        <h1>YouTube 設定</h1>
        <p className="section-desc">管理 YouTube 頻道授權、發布流程預設資源與 API 配額；共用 Google Sheet 請至「全域與 Google 設定」。</p>
      </header>

      {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}

      <div className="glass-panel card-padding settings-card card-stack">
        <div className="card-header">
          <div className="card-header-title"><Youtube size={20} color="#ff4d6d" /><h2 className="settings-heading">YouTube 頻道 Google 授權</h2></div>
          {youtubeConnected
            ? <span className="badge badge-connected"><CheckCircle2 size={14} /> 已連線：{youtubeUser.email || 'YouTube 帳號'}</span>
            : <span className="badge badge-disconnected"><XCircle size={14} /> 尚未連結</span>}
        </div>
        <div className="info-banner">
          <Youtube size={18} />
          <span>這個授權與控制台登入完全分開。請在 Google 授權視窗選擇「管理品牌帳號的 Google 帳號」，YouTube API 將使用該帳號可管理的頻道。</span>
        </div>
        {youtubeConnected && <div className="settings-grid">
          <div className="glass-panel settings-info-card"><strong>授權帳號</strong><p>{youtubeUser.email || '—'}</p></div>
          <div className="glass-panel settings-info-card"><strong>Token 狀態</strong><p>{tokenStatusLabel(youtube.token_status)}</p></div>
          <div className="glass-panel settings-info-card"><strong>最近更新</strong><p>{formatTokenDate(youtube.last_refreshed_at)}</p></div>
          <div className="glass-panel settings-info-card"><strong>目前到期時間</strong><p>{formatTokenDate(youtube.token_expires_at)}</p></div>
        </div>}
        {youtube.last_refresh_error && <div className="info-banner"><XCircle size={16} /><span>YouTube 授權 Token 最近更新未成功，請重新授權管理品牌帳號的 Google 帳號。</span></div>}
        <p className="section-desc">重新授權會替換目前保存的 YouTube 頻道連線，但不會登出控制台，也不會改變共用 Google Sheet 的登入帳號。</p>
        <div className="page-actions settings-card-actions"><button className="btn btn-primary" onClick={handleStartYoutubeOAuth} type="button" disabled={youtubeConnecting}>
          {youtubeConnecting ? <><span className="login-spinner"></span> 正在傳送至 Google 授權...</> : <><ExternalLink size={16} /> {youtubeConnected ? '重新授權 YouTube 頻道' : '連結 YouTube 頻道 Google 帳號'}</>}
        </button></div>
      </div>

      <form className="glass-panel card-padding settings-card card-stack" onSubmit={handleSave}>
        <div>
          <h2 className="settings-heading"><PlaySquare size={20} color="var(--secondary)" /> YouTube 發布預設資源</h2>
          <p className="section-desc">這個播放清單是 YouTube 發布與清理流程的 fallback。Video／Shorts 草稿頁若保存了自己的播放清單，會優先使用工作流設定；欄位修改後會自動儲存。</p>
        </div>
        <div className="form-group">
          <label className="form-label"><PlaySquare size={14} /> 預設 To-Post 播放清單 ID</label>
          <SourceLinkInput value={playlistId} onChange={(event) => handleChange('playlistId', event.target.value)} sourceType="youtube-playlist" placeholder="YouTube Playlist ID" />
        </div>
        <div className="responsive-grid youtube-quota-grid">
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
        <div className="page-actions settings-card-actions"><button className="btn btn-success" type="submit" disabled={saving}><Save size={18} />{saving ? '儲存中...' : '立即儲存 YouTube 設定'}</button></div>
      </form>

      <section className="glass-panel card-padding settings-card card-stack">
        <div>
          <h2 className="settings-heading">YouTube 草稿工作流設定</h2>
          <p className="section-desc">Video 與 Shorts 的工作表、欄位與工作流資源會分別保存；Sheet 內容複製、Video、Shorts 共用團體與人物篩選。</p>
        </div>
        <div className="responsive-grid youtube-workflow-grid">
          <div className="glass-panel youtube-workflow-card card-stack">
            <h3 className="youtube-workflow-heading"><Clapperboard size={18} /> Video 草稿</h3>
            <p className="section-desc">管理 Video 專屬工作表與欄位，人物篩選會與其他流程共用。</p>
            <button className="btn btn-secondary settings-inline-button" type="button" onClick={() => setActiveTab('youtube_video_drafts')}>前往 Video 設定 <ArrowRight size={16} /></button>
          </div>
          <div className="glass-panel youtube-workflow-card card-stack">
            <h3 className="youtube-workflow-heading"><Smartphone size={18} /> Shorts 草稿</h3>
            <p className="section-desc">管理 Shorts 專屬工作表與欄位，人物篩選會與其他流程共用。</p>
            <button className="btn btn-secondary settings-inline-button" type="button" onClick={() => setActiveTab('youtube_shorts_drafts')}>前往 Shorts 設定 <ArrowRight size={16} /></button>
          </div>
        </div>
      </section>
    </div>
  );
}

import React, { useEffect, useMemo, useState } from 'react';
import { ArrowRight, CheckCircle2, Clapperboard, ExternalLink, PlaySquare, Save, Smartphone, XCircle, Youtube } from 'lucide-react';
import { api, normalizeYoutubePlaylistInput } from '../services/api';
import { useToast } from '../components/Toast';
import SourceLinkInput from '../components/SourceLinkInput';
import ConfirmDialog from '../components/ConfirmDialog';

const SLOT_ORDER = ['primary', 'secondary'];

export function initialSettings(defaultPlaylistId, quotaLimit, quotaBuffer) {
  return {
    playlistId: defaultPlaylistId || '',
    quotaLimit: quotaLimit ?? 10000,
    quotaBuffer: quotaBuffer ?? 1000,
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

export function normalizeSlotRecord(slot, record) {
  const canBeActive = record?.can_be_active === undefined
    ? Boolean(record?.authenticated)
    : Boolean(record.can_be_active);
  return {
    slot,
    label: record?.label || (slot === 'primary' ? 'Primary' : 'Secondary'),
    configured: Boolean(record?.configured),
    enabled: Boolean(record?.enabled),
    authenticated: Boolean(record?.authenticated),
    can_be_active: canBeActive,
    channel_mismatch: Boolean(record?.channel_mismatch),
    user: record?.user || null,
    channel_id: record?.channel_id || null,
    channel_title: record?.channel_title || null,
    token_status: record?.token_status || 'not_connected',
    token_expires_at: record?.token_expires_at,
    last_refreshed_at: record?.last_refreshed_at,
    last_refresh_error: record?.last_refresh_error,
    client_fingerprint: record?.client_fingerprint,
    quota_limit: Number(record?.quota_limit ?? 10000),
    safety_buffer_units: Number(record?.safety_buffer_units ?? 1000),
  };
}

export default function YouTubeSettingsPage({ authUser, sysSettings = {}, refreshSettings, refreshAuthUser, setActiveTab }) {
  const toast = useToast();
  const youtube = useMemo(() => authUser?.youtube || {}, [authUser?.youtube]);
  const initial = useMemo(
    () => initialSettings(sysSettings.default_playlist_id, sysSettings.quota_limit, sysSettings.safety_buffer_units),
    [sysSettings.default_playlist_id, sysSettings.quota_limit, sysSettings.safety_buffer_units],
  );
  const slotRecords = useMemo(() => SLOT_ORDER.reduce((all, slot) => {
    all[slot] = normalizeSlotRecord(slot, youtube.slots?.[slot]);
    return all;
  }, {}), [youtube]);
  const [playlistId, setPlaylistId] = useState(initial.playlistId);
  const [slotDrafts, setSlotDrafts] = useState(() => Object.fromEntries(
    SLOT_ORDER.map((slot) => [slot, {
      quotaLimit: slotRecords[slot].quota_limit,
      quotaBuffer: slotRecords[slot].safety_buffer_units,
    }]),
  ));
  const [activeSlot, setActiveSlot] = useState(youtube.active_slot || 'primary');
  const [busyAction, setBusyAction] = useState(null);
  const [disconnectTarget, setDisconnectTarget] = useState(null);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    setPlaylistId(initial.playlistId);
  }, [initial.playlistId]);

  useEffect(() => {
    setActiveSlot(youtube.active_slot || 'primary');
    setSlotDrafts(Object.fromEntries(SLOT_ORDER.map((slot) => [slot, {
      quotaLimit: slotRecords[slot].quota_limit,
      quotaBuffer: slotRecords[slot].safety_buffer_units,
    }])));
  }, [slotRecords, youtube.active_slot]);

  const saveSlot = async (slot) => {
    const draft = slotDrafts[slot];
    const limit = Number(draft.quotaLimit);
    const buffer = Number(draft.quotaBuffer);
    if (!Number.isInteger(limit) || limit <= 0 || !Number.isInteger(buffer) || buffer < 0 || buffer >= limit) {
      const message = 'quota limit 必須大於 0，安全保留必須大於等於 0 且小於 quota limit。';
      setMsg({ type: 'error', text: message });
      toast.error(message);
      return;
    }
    setBusyAction({ kind: 'quota', slot });
    setMsg(null);
    try {
      await api.updateYoutubeQuota({
        slot,
        quotaLimit: limit,
        safetyBufferUnits: buffer,
      });
      await refreshSettings();
      if (refreshAuthUser) await refreshAuthUser();
      setMsg({ type: 'success', text: `${slotRecords[slot].label} 設定已儲存。` });
      toast.success(`${slotRecords[slot].label} 設定已儲存`);
    } catch (error) {
      setMsg({ type: 'error', text: error.message || '儲存失敗。' });
      toast.error(`儲存失敗：${error.message || '未知錯誤'}`);
    } finally {
      setBusyAction(null);
    }
  };

  const saveResources = async (event) => {
    event.preventDefault();
    const normalizedPlaylistId = normalizeYoutubePlaylistInput(playlistId);
    if (playlistId.trim() && !normalizedPlaylistId) {
      const message = '請輸入合法的 YouTube 播放清單網址或 ID。';
      setMsg({ type: 'error', text: message });
      toast.error(message);
      return;
    }
    setBusyAction({ kind: 'playlist' });
    setMsg(null);
    try {
      await api.updateYoutubePlaylist({
        playlistId: normalizedPlaylistId,
      });
      await refreshSettings();
      setPlaylistId(normalizedPlaylistId);
      setMsg({ type: 'success', text: '預設播放清單已儲存。' });
      toast.success('預設播放清單已儲存');
    } catch (error) {
      setMsg({ type: 'error', text: error.message || '儲存失敗。' });
      toast.error(`儲存失敗：${error.message || '未知錯誤'}`);
    } finally {
      setBusyAction(null);
    }
  };

  const updateDraft = (slot, field, value) => {
    setSlotDrafts((current) => ({ ...current, [slot]: { ...current[slot], [field]: value } }));
  };

  const startOAuth = async (slot) => {
    if (busyAction) return;
    setBusyAction({ kind: 'authorization', slot });
    try {
      const result = await api.getYoutubeAuthUrl(slot);
      if (!result.auth_url) throw new Error('無法取得 Google 授權網址，請稍後再試。');
      window.location.href = result.auth_url;
    } catch (error) {
      toast.error(`取得 ${slotRecords[slot].label} 授權網址失敗：${error.message || '未知錯誤'}`);
      setBusyAction(null);
    }
  };

  const activateSlot = async (slot) => {
    if (busyAction || !slotRecords[slot].can_be_active) return;
    setBusyAction({ kind: 'authorization', slot });
    try {
      await api.activateYoutubeSlot(slot);
      setActiveSlot(slot);
      if (refreshAuthUser) await refreshAuthUser();
      toast.success(`已將 ${slotRecords[slot].label} 設為作用中 slot`);
    } catch (error) {
      toast.error(`切換 slot 失敗：${error.message || '未知錯誤'}`);
    } finally {
      setBusyAction(null);
    }
  };

  const requestDisconnect = (slot) => {
    if (busyAction) return;
    const isActive = activeSlot === slot;
    setDisconnectTarget({ slot, isActive });
  };

  const disconnectSlot = async () => {
    if (!disconnectTarget || busyAction) return;
    const { slot } = disconnectTarget;
    setDisconnectTarget(null);
    setBusyAction({ kind: 'authorization', slot });
    try {
      await api.disconnectYoutube(slot, { confirm: true });
      if (refreshAuthUser) await refreshAuthUser();
      toast.success(`${slotRecords[slot].label} 已斷開`);
    } catch (error) {
      toast.error(`斷開失敗：${error.message || '未知錯誤'}`);
    } finally {
      setBusyAction(null);
    }
  };

  const pageBusy = Boolean(busyAction);
  const authorizationBusy = busyAction?.kind === 'authorization';
  const disconnectRecord = disconnectTarget ? slotRecords[disconnectTarget.slot] : null;
  const disconnectMessage = disconnectTarget?.isActive
    ? `這是目前作用中的 ${disconnectRecord?.label || 'YouTube'} 授權組合。斷開後，新的 YouTube request 將暫時無法執行，直到另一個可用組合設為作用中或重新授權。確定要斷開嗎？`
    : `將移除 ${disconnectRecord?.label || '此組合'} 的 YouTube 授權；目前作用中的 request context 不受影響。確定要斷開嗎？`;

  return (
    <div className="section-gap settings-page youtube-settings-page">
      <header className="page-header">
        <h1>YouTube 設定</h1>
        <p className="section-desc">管理兩組 YouTube OAuth slot、頻道一致性、作用中 request context、發布預設資源與各 project quota。跨 project 不會自動切換重試。</p>
      </header>

      {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}

      <div className="responsive-grid youtube-slot-grid">
        {SLOT_ORDER.map((slot) => {
          const record = slotRecords[slot];
          const draft = slotDrafts[slot];
          const isActive = activeSlot === slot;
          const busy = busyAction?.slot === slot;
          return (
            <section className="glass-panel card-padding settings-card card-stack" key={slot}>
              <div className="card-header">
                <div className="card-header-title"><Youtube size={20} color="#ff4d6d" /><h2 className="settings-heading">{record.label}</h2></div>
                {isActive && <span className="badge badge-info">目前作用中</span>}
                {record.authenticated
                  ? <span className="badge badge-connected"><CheckCircle2 size={14} /> 已授權</span>
                  : <span className="badge badge-disconnected"><XCircle size={14} /> {record.configured ? '尚未授權' : '未配置'}</span>}
              </div>

              {!record.configured && <div className="info-banner"><XCircle size={16} /><span>此 slot 尚未由伺服器配置 OAuth Client；前端不會接觸 client secret。</span></div>}
              {record.channel_mismatch && <div className="info-banner"><XCircle size={16} /><span>此 slot 的 Channel ID 與另一個 slot 不一致，因此不能設為作用中；請重新授權同一頻道。</span></div>}

              <div className="settings-grid">
                <div className="glass-panel settings-info-card"><strong>Google 帳號</strong><p>{record.user?.email || '—'}</p></div>
                <div className="glass-panel settings-info-card"><strong>YouTube Channel</strong><p>{record.channel_title || record.channel_id || '尚未驗證'}</p></div>
                <div className="glass-panel settings-info-card"><strong>Token 狀態</strong><p>{tokenStatusLabel(record.token_status)}</p></div>
                <div className="glass-panel settings-info-card"><strong>Token 到期</strong><p>{formatTokenDate(record.token_expires_at)}</p></div>
                <div className="glass-panel settings-info-card"><strong>最近 refresh</strong><p>{formatTokenDate(record.last_refreshed_at)}</p></div>
                <div className="glass-panel settings-info-card"><strong>Client fingerprint</strong><p>{record.client_fingerprint || '—'}</p></div>
              </div>
              {record.last_refresh_error && <div className="info-banner"><XCircle size={16} /><span>Token refresh 失敗，請重新授權此 slot。</span></div>}

              <div className="responsive-grid youtube-quota-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor={`${slot}-quota-limit`}>Project 一般 quota</label>
                  <input id={`${slot}-quota-limit`} className="form-input" type="number" min="1" step="1" value={draft.quotaLimit} onChange={(event) => updateDraft(slot, 'quotaLimit', event.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor={`${slot}-quota-buffer`}>安全保留 units</label>
                  <input id={`${slot}-quota-buffer`} className="form-input" type="number" min="0" step="1" value={draft.quotaBuffer} onChange={(event) => updateDraft(slot, 'quotaBuffer', event.target.value)} />
                </div>
              </div>
              <p className="section-desc">此 ledger 只記錄 {record.label}；quotaExceeded 只封鎖這個 slot，不會自動跨 project 重試。</p>

              <div className="page-actions settings-card-actions">
                <button className="btn btn-primary" onClick={() => startOAuth(slot)} type="button" disabled={!record.configured || pageBusy || authorizationBusy}>
                  {busy ? <><span className="login-spinner"></span> 處理中...</> : <><ExternalLink size={16} /> {record.authenticated ? '重新授權' : '連結此 slot'}</>}
                </button>
                <button className="btn btn-success" onClick={() => saveSlot(slot)} type="button" disabled={pageBusy}><Save size={16} />儲存 slot 設定</button>
                {record.can_be_active && !isActive && <button className="btn btn-secondary" onClick={() => activateSlot(slot)} type="button" disabled={pageBusy || authorizationBusy}>設為作用中</button>}
                {record.authenticated && <button className="btn" onClick={() => requestDisconnect(slot)} type="button" disabled={pageBusy || authorizationBusy}>斷開</button>}
              </div>
            </section>
          );
        })}
      </div>

      <form className="glass-panel card-padding settings-card card-stack" onSubmit={saveResources}>
        <div>
          <h2 className="settings-heading"><PlaySquare size={20} color="var(--secondary)" /> YouTube 發布預設資源</h2>
          <p className="section-desc">這個播放清單是 YouTube 發布與清理流程的 fallback。Video／Shorts 草稿頁若保存了自己的播放清單，會優先使用工作流設定。</p>
        </div>
        <div className="form-group">
          <label className="form-label"><PlaySquare size={14} /> 預設 To-Post 播放清單</label>
          <SourceLinkInput value={playlistId} onChange={(event) => setPlaylistId(event.target.value)} sourceType="youtube-playlist" placeholder="YouTube Playlist ID 或網址" />
        </div>
        <div className="page-actions settings-card-actions"><button className="btn btn-success" type="submit" disabled={pageBusy}><Save size={18} />{busyAction?.kind === 'playlist' ? '儲存中...' : '儲存預設播放清單'}</button></div>
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

      <ConfirmDialog
        open={Boolean(disconnectTarget)}
        title={`確認斷開 ${disconnectRecord?.label || 'YouTube'} 授權`}
        message={disconnectMessage}
        confirmText="確認斷開"
        cancelText="取消"
        variant="destructive"
        onConfirm={disconnectSlot}
        onCancel={() => { if (!busyAction) setDisconnectTarget(null); }}
      />
    </div>
  );
}

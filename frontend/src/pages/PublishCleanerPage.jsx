import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, normalizeYoutubePlaylistInput } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import ThumbnailDialog from '../components/ThumbnailDialog';
import YouTubeVideoEditDialog from '../components/YouTubeVideoEditDialog';
import useAccountWorkState from '../hooks/useAccountWorkState';
import { sortVideosByUploadTime } from '../utils/videoOrder';
import { youtubeIsConnected, youtubePreferredUiSlot, youtubeRoutingMode, youtubeRoutingReasonLabel } from '../utils/youtubeRouting';
import SourceLinkInput from '../components/SourceLinkInput';
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Globe,
  ListOrdered,
  Pencil,
  PlaySquare,
  RefreshCw,
  Send,
  Trash2,
} from 'lucide-react';

function youtubeVideoUrl(videoId) {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
}
function normalizePlaylistId(value) {
  return normalizeYoutubePlaylistInput(value);
}

function youtubeAuthorizationFingerprint(youtube) {
  const slots = ['primary', 'secondary'].map((slot) => {
    const record = youtube?.slots?.[slot] || {};
    return [
      slot,
      record.configured,
      record.authenticated,
      record.channel_id,
      record.client_fingerprint,
      record.token_status,
      record.token_expires_at,
      record.last_refreshed_at,
    ];
  });
  return JSON.stringify({
    activeSlot: youtube?.active_slot || 'primary',
    routingMode: youtubeRoutingMode(youtube),
    slots,
  });
}

function normalizeVersion(value) {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function getYoutubeAuthContext(authUser, slotOverride = '') {
  const youtube = authUser?.youtube || {};
  const slot = slotOverride || youtubePreferredUiSlot(youtube);
  const record = youtube.slots?.[slot] || {};
  const user = record.user || {};
  return {
    slot,
    channelId: record.channel_id || '',
    channelTitle: record.channel_title || '',
    account: user.sub || user.email || '',
    clientFingerprint: record.client_fingerprint || '',
    authenticated: Boolean(record.authenticated) || youtubeIsConnected(youtube),
    tokenStatus: record.token_status || '',
    tokenExpiresAt: record.token_expires_at || '',
    lastRefreshedAt: record.last_refreshed_at || '',
    routingMode: youtubeRoutingMode(youtube),
    authorizationFingerprint: youtubeAuthorizationFingerprint(youtube),
  };
}

function authContextKey(context) {
  return JSON.stringify({
    slot: context.slot,
    channelId: context.channelId,
    channelTitle: context.channelTitle,
    account: context.account,
    clientFingerprint: context.clientFingerprint,
    authenticated: context.authenticated,
    tokenStatus: context.tokenStatus,
    tokenExpiresAt: context.tokenExpiresAt,
    lastRefreshedAt: context.lastRefreshedAt,
    routingMode: context.routingMode,
    authorizationFingerprint: context.authorizationFingerprint,
  });
}

function formatAuthContext(context) {
  const channel = context.channelTitle || context.channelId;
  const channelText = channel ? `／頻道 ${channel}` : '';
  const accountText = context.account ? `／帳號 ${context.account}` : '';
  return `${context.slot}${channelText}${accountText}`;
}

function getCurrentYoutubeDataVersion(authUser, sysSettings, authContext) {
  const slot = authUser?.youtube?.slots?.[authContext.slot] || {};
  return normalizeVersion(
    authUser?.youtube?.data_version
      ?? authUser?.youtube?.dataVersion
      ?? slot.data_version
      ?? slot.dataVersion
      ?? sysSettings?.youtube_data_version
      ?? sysSettings?.youtubeDataVersion,
  );
}

function getPreviewSnapshot(response) {
  return response?.preview_snapshot
    ?? response?.previewSnapshot
    ?? response?.preview?.snapshot
    ?? response?.snapshot
    ?? null;
}

function getPreviewToken(response) {
  return response?.preview_token
    ?? response?.previewToken
    ?? response?.snapshot_token
    ?? response?.snapshotToken
    ?? response?.preview?.token
    ?? null;
}

function getDataVersion(response, previewSnapshot) {
  return normalizeVersion(
    response?.data_version
      ?? response?.dataVersion
      ?? response?.version
      ?? previewSnapshot?.data_version
      ?? previewSnapshot?.dataVersion,
  );
}

function snapshotMatches(snapshot, {
  playlistId,
  authKey,
  dataVersion,
  workflowRevision,
}) {
  if (!snapshot || snapshot.revision !== workflowRevision) return false;
  if (snapshot.playlistId !== playlistId || snapshot.authKey !== authKey) return false;
  if (dataVersion !== null && snapshot.dataVersion !== dataVersion) return false;
  return true;
}

function cloneConfirmationSnapshot(snapshot) {
  return {
    ...snapshot,
    videos: snapshot.videos.map((video) => ({ ...video })),
  };
}

function buildFallbackPreviewSnapshot(snapshot) {
  return {
    playlist_id: snapshot.playlistId,
    youtube_slot: snapshot.auth.slot,
    data_version: snapshot.dataVersion,
    video_ids: snapshot.videos.map((video) => video.video_id),
  };
}

function buildPublishOptions(snapshot) {
  const previewSnapshot = snapshot.previewSnapshot ?? buildFallbackPreviewSnapshot(snapshot);
  return {
    youtubeSlot: previewSnapshot?.youtube_slot || snapshot.auth.slot,
    previewSnapshot,
    previewToken: snapshot.previewToken,
  };
}

function YouTubeVideoLink({ videoId }) {
  if (!videoId) return null;
  return (
    <a className="youtube-video-link" href={youtubeVideoUrl(videoId)} target="_blank" rel="noopener noreferrer">
      <ExternalLink size={14} aria-hidden="true" />
      在 YouTube 開啟影片
    </a>
  );
}

export default function PublishCleanerPage({ sysSettings = {}, authUser }) {
  const toast = useToast();
  const { value: saved, error: workStateError } = useAccountWorkState('youtube_publish_cleaner', {});
  const initialPlaylistId = sysSettings.default_playlist_id || saved?.playlistId || '';
  const [playlistId, setPlaylistId] = useState(initialPlaylistId);
  const [playlistSnapshot, setPlaylistSnapshot] = useState(null);
  const [loadStatus, setLoadStatus] = useState('idle');
  const authContext = useMemo(() => getYoutubeAuthContext(authUser), [authUser]);
  const routingMode = youtubeRoutingMode(authUser?.youtube);
  const authKey = useMemo(() => authContextKey(authContext), [authContext]);
  const dataVersion = useMemo(
    () => getCurrentYoutubeDataVersion(authUser, sysSettings, authContext),
    [authContext, authUser, sysSettings],
  );
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmationSnapshot, setConfirmationSnapshot] = useState(null);
  const [previewImage, setPreviewImage] = useState(null);
  const [quotaEstimate, setQuotaEstimate] = useState(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [editingVideo, setEditingVideo] = useState(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const workflowRevisionRef = useRef(0);
  const playlistIdRef = useRef(initialPlaylistId);
  const sharedPlaylistIdRef = useRef(normalizePlaylistId(sysSettings.default_playlist_id));
  const currentAuthKeyRef = useRef(authKey);
  const currentDataVersionRef = useRef(dataVersion);
  const contextRef = useRef({ authKey, dataVersion });
  const loadingRef = useRef(false);
  const executingRef = useRef(false);
  const estimateLockRef = useRef(false);
  const executionLockRef = useRef(false);
  const executionIdRef = useRef(0);

  playlistIdRef.current = playlistId;
  currentAuthKeyRef.current = authKey;
  currentDataVersionRef.current = dataVersion;

  const invalidateSnapshot = useCallback(() => {
    workflowRevisionRef.current += 1;
    loadingRef.current = false;
    estimateLockRef.current = false;
    setLoading(false);
    setPlaylistSnapshot(null);
    setLoadStatus('idle');
    setConfirmationSnapshot(null);
    setConfirmOpen(false);
    setQuotaEstimate(null);
    setEstimateLoading(false);
    setEditingVideo(null);
    setResult(null);
    setErrorMsg(null);
  }, []);

  useEffect(() => {
    const previous = contextRef.current;
    const changed = previous.authKey !== authKey || previous.dataVersion !== dataVersion;
    contextRef.current = { authKey, dataVersion };
    if (changed) invalidateSnapshot();
  }, [authKey, dataVersion, invalidateSnapshot]);

  useEffect(() => {
    const sharedPlaylistId = normalizePlaylistId(sysSettings.default_playlist_id);
    if (sharedPlaylistId === sharedPlaylistIdRef.current) return;
    sharedPlaylistIdRef.current = sharedPlaylistId;
    if (sharedPlaylistId !== normalizePlaylistId(playlistIdRef.current)) {
      playlistIdRef.current = sharedPlaylistId;
      invalidateSnapshot();
      setPlaylistId(sharedPlaylistId);
    }
  }, [invalidateSnapshot, sysSettings.default_playlist_id]);

  const currentSnapshot = snapshotMatches(playlistSnapshot, {
    playlistId: normalizePlaylistId(playlistId),
    authKey,
    dataVersion,
    workflowRevision: workflowRevisionRef.current,
  }) ? playlistSnapshot : null;
  const videos = currentSnapshot?.videos || [];
  const sourceLabel = currentSnapshot?.source === 'youtube-api' ? 'YouTube API' : '';
  const dialogSnapshot = snapshotMatches(confirmationSnapshot, {
    playlistId: normalizePlaylistId(playlistId),
    authKey,
    dataVersion,
    workflowRevision: workflowRevisionRef.current,
  }) ? confirmationSnapshot : null;

  const isRequestCurrent = (revision, requestedPlaylistId, requestedAuthKey, requestedDataVersion) => (
    revision === workflowRevisionRef.current
      && requestedPlaylistId === normalizePlaylistId(playlistIdRef.current)
      && requestedAuthKey === currentAuthKeyRef.current
      && requestedDataVersion === currentDataVersionRef.current
  );

  const handlePlaylistIdChange = (event) => {
    if (executingRef.current) return;
    const nextPlaylistId = event.target.value;
    playlistIdRef.current = nextPlaylistId;
    if (nextPlaylistId !== playlistId) invalidateSnapshot();
    setPlaylistId(nextPlaylistId);
  };

  const handleLoadPlaylist = async () => {
    if (loadingRef.current || executingRef.current) return;
    if (!authUser) {
      toast.warning('請先登入控制台！');
      return;
    }
    if (!authContext.authenticated) {
      toast.warning('請先在「YouTube 設定」連結 YouTube 頻道 Google 帳號！');
      return;
    }
    const requestedPlaylistId = normalizePlaylistId(playlistId);
    if (!requestedPlaylistId) {
      toast.warning('請先輸入 To-Post 播放清單 ID！');
      return;
    }

    invalidateSnapshot();
    const requestRevision = workflowRevisionRef.current;
    const requestedAuthKey = authKey;
    const requestedDataVersion = dataVersion;
    const requestedAuthContext = authContext;
    loadingRef.current = true;
    setLoading(true);
    setLoadStatus('loading');
    setErrorMsg(null);
    setResult(null);
    setEditingVideo(null);

    try {
      const response = await api.getPlaylistVideos(requestedPlaylistId);
      if (!isRequestCurrent(requestRevision, requestedPlaylistId, requestedAuthKey, requestedDataVersion)) return;

      const serverPreviewSnapshot = getPreviewSnapshot(response);
      const responseSlot = response?.youtube_slot
        || (serverPreviewSnapshot && typeof serverPreviewSnapshot === 'object' ? serverPreviewSnapshot.youtube_slot : '');
      const responseAuthContext = responseSlot
        ? getYoutubeAuthContext(authUser, responseSlot)
        : requestedAuthContext;

      const loadedVideos = sortVideosByUploadTime(Array.isArray(response?.videos) ? response.videos : []);
      const loadedDataVersion = getDataVersion(response, serverPreviewSnapshot);
      const resolvedPlaylistId = normalizePlaylistId(response?.playlist_id) || requestedPlaylistId;
      const previewToken = getPreviewToken(response);
      if (!previewToken || !serverPreviewSnapshot) {
        setPlaylistSnapshot(null);
        setLoadStatus('error');
        setErrorMsg('伺服器未提供可驗證的播放清單預覽，已安全停止；請重新讀取。');
        return;
      }
      const snapshot = {
        playlistId: resolvedPlaylistId,
        videos: loadedVideos,
        source: response?.source || '',
        fallbackReason: response?.fallback_reason || '',
        routingReason: response?.youtube_slot_reason || serverPreviewSnapshot?.youtube_slot_reason || '',
        auth: responseAuthContext,
        authKey: requestedAuthKey,
        dataVersion: loadedDataVersion,
        previewSnapshot: serverPreviewSnapshot,
        previewToken,
        revision: requestRevision,
      };
      setPlaylistSnapshot(snapshot);
      setLoadStatus(loadedVideos.length ? 'ready' : 'empty');
    } catch (error) {
      if (!isRequestCurrent(requestRevision, requestedPlaylistId, requestedAuthKey, requestedDataVersion)) return;
      setPlaylistSnapshot(null);
      setLoadStatus('error');
      setErrorMsg(`讀取 To-Post 播放清單失敗：${error.message}`);
    } finally {
      if (requestRevision === workflowRevisionRef.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  };

  const requestPublish = async () => {
    if (estimateLockRef.current || executingRef.current || loadingRef.current) return;
    if (!currentSnapshot || !videos.length) {
      toast.warning('請先讀取有影片的 To-Post 播放清單！');
      return;
    }

    const requestRevision = workflowRevisionRef.current;
    const candidateSnapshot = currentSnapshot;
    const requestedPlaylistId = normalizePlaylistId(playlistId);
    const requestedAuthKey = authKey;
    const requestedDataVersion = dataVersion;
    estimateLockRef.current = true;
    setEstimateLoading(true);
    setQuotaEstimate(null);
    try {
      const estimate = await api.estimateYoutubeQuota({
        operation: 'youtube.publish_cleanup',
        itemCount: candidateSnapshot.videos.length,
        slot: candidateSnapshot.auth.slot,
      });
      if (!isRequestCurrent(requestRevision, requestedPlaylistId, requestedAuthKey, requestedDataVersion)) return;
      setQuotaEstimate(estimate);
    } catch (error) {
      if (!isRequestCurrent(requestRevision, requestedPlaylistId, requestedAuthKey, requestedDataVersion)) return;
      setQuotaEstimate(null);
      toast.warning(`無法取得 quota 預估，仍可直接執行：${error.message}`);
    } finally {
      estimateLockRef.current = false;
      if (requestRevision === workflowRevisionRef.current) setEstimateLoading(false);
    }

    if (!isRequestCurrent(requestRevision, requestedPlaylistId, requestedAuthKey, requestedDataVersion)) return;
    setConfirmationSnapshot(cloneConfirmationSnapshot(candidateSnapshot));
    setConfirmOpen(true);
  };

  const doPublish = async () => {
    if (executionLockRef.current || !dialogSnapshot) {
      if (!dialogSnapshot && confirmOpen) {
        setConfirmOpen(false);
        setConfirmationSnapshot(null);
        toast.warning('預覽資料已變更，請重新讀取播放清單後再執行。');
      }
      return;
    }

    executionLockRef.current = true;
    const executionId = ++executionIdRef.current;
    const requestRevision = workflowRevisionRef.current;
    const requestSnapshot = dialogSnapshot;
    const publishOptions = buildPublishOptions(requestSnapshot);
    setConfirmOpen(false);
    setConfirmationSnapshot(null);
    executingRef.current = true;
    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    setEditingVideo(null);
    try {
      const response = await api.publishAndCleanup(requestSnapshot.playlistId, publishOptions);
      if (requestRevision !== workflowRevisionRef.current) return;
      invalidateSnapshot();
      setResult(response);
      const summary = `成功 ${response.succeeded_count || 0} 支、警告 ${response.warning_count || 0} 支、略過 ${response.skipped_count || 0} 支、失敗 ${response.failed_count || 0} 支`;
      if (response.quota_blocked || response.not_attempted_count) toast.warning(`公開與清理部分完成：${summary}`);
      else if (response.failed_count || response.warning_count) toast.warning(`公開與清理完成但有需注意項目：${summary}`);
      else toast.success(`公開與清理完成：${summary}`);
    } catch (error) {
      if (requestRevision !== workflowRevisionRef.current) return;
      if (error.code === 'stale_preview' || error.status === 409) {
        invalidateSnapshot();
        setErrorMsg('預覽已過期或播放清單已變更，已安全停止發布與清理；請重新讀取清單。');
        toast.warning('預覽已過期，發布與清理已安全停止');
      } else {
        setErrorMsg(`發布與清理執行失敗：${error.message}`);
        toast.error('發布與清理執行失敗');
      }
    } finally {
      if (executionId === executionIdRef.current) {
        executionLockRef.current = false;
        executingRef.current = false;
        setExecuting(false);
      }
    }
  };

  const handleSaveEdit = async ({ title, description }) => {
    if (!editingVideo || savingEdit || executingRef.current) return;
    const editRevision = workflowRevisionRef.current;
    const editPlaylistId = normalizePlaylistId(playlistId);
    const editAuthKey = authKey;
    const editDataVersion = dataVersion;
    const videoId = editingVideo.video_id;
    setSavingEdit(true);
    try {
      const updated = await api.updateYoutubeVideoMetadata({ videoId, title, description });
      if (!isRequestCurrent(editRevision, editPlaylistId, editAuthKey, editDataVersion)) return;
      invalidateSnapshot();
      toast.success('影片標題與描述已更新，請重新讀取播放清單以建立最新預覽');
      void updated;
    } catch (error) {
      if (isRequestCurrent(editRevision, editPlaylistId, editAuthKey, editDataVersion)) {
        toast.error(`影片更新失敗：${error.message}`);
      }
    } finally {
      setSavingEdit(false);
    }
  };

  const metadataBlock = (title, description) => (
    <div className="metadata-block">
      <div>
        <div className="metadata-label">標題</div>
        <div className="metadata-title">{title || '無標題影片'}</div>
      </div>
      <div>
        <div className="metadata-label">描述</div>
        <div className="metadata-description">
          {description || '（無描述）'}
        </div>
      </div>
    </div>
  );

  const confirmationMessage = dialogSnapshot ? [
    `播放清單：${dialogSnapshot.playlistId}`,
    `授權組合：${formatAuthContext(dialogSnapshot.auth)}`,
    `影片數量：${dialogSnapshot.videos.length}`,
    '實際確認影片：',
    dialogSnapshot.videos.map((video, index) => (
      `#${index + 1} ${video.title || '無標題影片'}（${video.video_id}）`
    )).join('\n'),
    '以上影片才會送出；預覽後新加入清單或未出現在此清單的影片不會發布。',
    '影片設為公開後會自 To-Post 播放清單移除，但仍會保留在 YouTube 頻道中。',
    quotaEstimate ? `最壞估算 ${Number(quotaEstimate.projected_units || 0).toLocaleString()} units；目前配額預計可處理 ${quotaEstimate.max_items_today ?? dialogSnapshot.videos.length} 支。若途中達上限，未執行項目需在官方重設後重新送出。` : '',
  ].filter(Boolean).join('\n') : '';

  return (
    <div className="section-gap publish-cleaner-page">
      <ConfirmDialog
        open={confirmOpen && Boolean(dialogSnapshot) && !executing}
        title="確認公開並清理清單"
        message={confirmationMessage}
        confirmText="確認公開並移出 To-Post"
        cancelText="取消"
        variant="destructive"
        onConfirm={doPublish}
        onCancel={() => {
          setConfirmOpen(false);
          setConfirmationSnapshot(null);
        }}
      />

      <YouTubeVideoEditDialog
        video={editingVideo}
        saving={savingEdit}
        onSave={handleSaveEdit}
        onClose={() => setEditingVideo(null)}
      />

      <header className="page-header">
        <div className="section-header">
          <Send size={24} color="var(--secondary)" />
          <h1>YouTube｜公開 To-Post 影片並清理清單</h1>
        </div>
        <p className="section-desc">
          讀取待發布影片後，依 YouTube 上傳時間由最早到最晚顯示與處理；執行時才呼叫必要的 YouTube API 完成公開與移出清單。
        </p>
        <p className="section-desc">目前 YouTube routing：{routingMode === 'auto_primary' ? 'Auto：Primary 優先，quota 不足時使用 Secondary' : '手動：只使用目前作用中 slot'}。每次讀取的預覽會固定實際使用的 slot。</p>
      </header>

      <div className="glass-panel card-padding toolbar publish-source-panel">
        <div className="form-group publish-source-field">
          <label className="form-label"><PlaySquare size={14} /> 共用 To-Post 播放清單</label>
          <SourceLinkInput
            type="text"
            value={playlistId}
            onChange={handlePlaylistIdChange}
            sourceType="youtube-playlist"
            placeholder="YouTube Playlist ID"
            disabled={executing}
          />
        </div>
        <button className="btn btn-primary publish-action-button" onClick={handleLoadPlaylist} disabled={loading || executing || estimateLoading}>
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          {loading ? '讀取中...' : '讀取 To-Post 播放清單'}
        </button>
      </div>

      {workStateError && <div className="filter-panel-status filter-panel-status-error" role="alert">工作狀態同步失敗：{workStateError}</div>}

      {sourceLabel && (
        <div className="info-banner">
          <ListOrdered size={15} color="var(--secondary)" />
          <span>
            播放清單來源：{sourceLabel}。顯示與實際處理都依上傳時間由最早到最晚；缺少上傳時間的影片排在最後並維持原始順序。
            {currentSnapshot.fallbackReason ? ` 回退原因：${currentSnapshot.fallbackReason}` : ''}
            {currentSnapshot.routingReason ? ` YouTube routing：${youtubeRoutingReasonLabel(currentSnapshot.routingReason)}。` : ''}
          </span>
        </div>
      )}

      {loadStatus === 'empty' && currentSnapshot && (
        <div className="info-banner" role="status">
          <ListOrdered size={15} color="var(--secondary)" />
          <span>播放清單「{currentSnapshot.playlistId}」目前沒有影片，沒有可執行的發布項目。</span>
        </div>
      )}

      {errorMsg && <div className="glass-panel error-alert" role="alert"><AlertTriangle size={20} /><span>{errorMsg}</span></div>}

      {videos.length > 0 && currentSnapshot && (
        <div className="section-gap publish-workflow">
          <div className="glass-panel card-padding publish-summary-panel">
            <h2>確認公開並移除 {videos.length} 支影片</h2>
            <p>
              系統會依下方上傳時間順序逐支設為<strong>「公開（Public）」</strong>，成功後再從 To-Post 播放清單移除。移出播放清單不會刪除影片。
            </p>
          </div>

          <div className="publish-list">
            <h3 className="publish-list-heading">
              <ListOrdered size={18} /> 待處理影片清單（上傳時間：最早 → 最晚）：
            </h3>
            {videos.map((video, index) => (
              <div key={video.video_id} className="glass-panel publish-item">
                <span className="publish-item-index">#{index + 1}</span>
                {video.thumbnail_url && <button type="button" className="publish-cleaner-thumbnail-button" aria-label={`放大檢視${video.title || '影片'}縮圖`} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.title })}><img className="publish-cleaner-thumbnail" src={video.thumbnail_url} alt="" /></button>}
                <div className="publish-item-content">
                  {metadataBlock(video.title, video.description)}
                  <YouTubeVideoLink videoId={video.video_id} />
                  <div className="publish-item-meta">
                    <span>ID: {video.video_id}</span>
                    <span>
                      上傳時間：{video.published_at ? new Date(video.published_at).toLocaleString() : '未提供（排在最後）'}
                    </span>
                  </div>
                </div>
                <div className="publish-item-status">
                  <span className="badge badge-info"><Globe size={12} /> 將設為公開</span>
                  <span className="badge badge-info publish-remove-badge"><Trash2 size={12} /> 移出清單</span>
                  <button
                    type="button"
                    className="btn btn-secondary publish-edit-button"
                    onClick={() => setEditingVideo(video)}
                    disabled={executing || savingEdit || loading || estimateLoading}
                    aria-label={`編輯影片 ${video.title || video.video_id}`}
                  >
                    <Pencil size={14} aria-hidden="true" /> 編輯
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="glass-panel execution-bar">
            <span>確認上傳時間、標題與描述無誤後，啟動發布流程：</span>
            <button className="btn btn-primary publish-action-button" onClick={requestPublish} disabled={executing || loading || estimateLoading || !currentSnapshot || !videos.length}>
              <Send size={18} /> {executing ? '逐支發布並清理中...' : '確認公開並移出 To-Post'}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="glass-panel card-padding publish-result-panel card-stack">
          <h3 className={result.completed ? 'result-heading result-heading-publish-success' : 'result-heading result-heading-warning'}><CheckCircle2 size={22} /> {result.completed ? '公開與清理已執行完成' : '公開與清理部分完成'}</h3>
          <p className="section-desc">共 {result.total_count || 0} 支：成功 {result.succeeded_count || 0}、警告 {result.warning_count || 0}、略過 {result.skipped_count || 0}、失敗 {result.failed_count || 0}、未執行 {result.not_attempted_count || 0}。</p>
          {result.quota_blocked && <div className="info-banner"><AlertTriangle size={15} /><span>已達 YouTube 配額上限；未執行項目請於官方重設後重新讀取播放清單並送出。</span></div>}
          {result.results && <div className="publish-result-list">
            {result.results.map((item, index) => (
              <div key={`${item.video_id}-${index}`} className={`result-item result-row publish-result-item ${item.status === 'failed' ? 'publish-result-item-failed' : 'publish-result-item-success'}`}>
                <div>
                  <strong>#{index + 1}</strong>
                  <div className="publish-result-metadata">{metadataBlock(item.title, item.description)}</div>
                  <div className="result-meta">ID: {item.video_id} · <YouTubeVideoLink videoId={item.video_id} /></div>
                  {item.reason && <div className={item.status === 'failed' ? 'result-reason result-reason-failed' : 'result-reason'}>說明：{item.reason}</div>}
                </div>
                <span className={`badge ${item.status === 'succeeded' ? 'badge-connected' : item.status === 'failed' ? 'badge-disconnected' : 'badge-warning'}`}>{item.status === 'succeeded' ? '完成' : item.status === 'succeeded_with_warnings' ? '完成但有警告' : item.status === 'failed' ? '失敗' : item.status === 'skipped' ? '略過' : '未執行'}</span>
              </div>
            ))}
          </div>}
        </div>
      )}

      <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}

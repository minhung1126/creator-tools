import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ExternalLink, ListVideo, Loader2, Play, RefreshCw, Square, Upload } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../services/api';
import SourceLinkInput from '../components/SourceLinkInput';
import { StatusMessage } from '../components/StatusMessage';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { saveOAuthReturnPath } from '../utils/authReturnPath';
import { PATHS } from '../routes/paths';

const ACTIVE_JOB_STATUSES = new Set(['queued', 'running', 'cancel_requested', 'paused']);
export const YOUTUBE_UPLOAD_POLL_INTERVAL_MS = 2000;

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function jobStatusLabel(status) {
  return {
    queued: '等待處理',
    running: '上傳中',
    cancel_requested: '準備取消',
    cancelled: '已取消',
    paused: '已暫停，等待重試',
    failed: '失敗',
    completed: '已完成',
  }[status] || status || '—';
}

function itemStatusLabel(item) {
  return {
    ready: '可上傳',
    upload: '等待上傳',
    pending: '等待上傳',
    downloading: '下載中',
    uploading: '上傳中',
    uploaded: '待加入 To-Post',
    added: '已加入 To-Post',
    skipped: '略過',
    cancelled: '已取消',
    failed: '失敗',
    already_uploaded: '已上傳，略過',
    already_queued: '已有工作，略過',
    resume_playlist: '待加入 To-Post',
  }[item?.status || item?.action] || item?.status || item?.action || '—';
}

function errorText(error, fallback = '操作失敗，請稍後重試。') {
  return error?.message || fallback;
}

function numericValue(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function firstBoolean(...values) {
  return values.find((value) => typeof value === 'boolean');
}

function quotaMetric(quota, bucket, names, fallback = null) {
  const bucketData = quota?.[bucket] || {};
  const candidates = names.flatMap((name) => [
    bucketData?.[name],
    bucketData?.[`${name}_units`],
    typeof quota?.[name] === 'object' ? quota[name]?.[bucket] : undefined,
    typeof quota?.[`${name}_units`] === 'object' ? quota[`${name}_units`]?.[bucket] : undefined,
  ]);
  return numericValue(candidates.find((value) => value !== undefined && value !== null), fallback);
}

function formatUnits(value) {
  const number = numericValue(value, 0);
  return number.toLocaleString('zh-TW');
}

function resetLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-TW');
}

function youtubeSlotLabel(slot) {
  if (slot === 'primary') return '主要授權組合';
  if (slot === 'secondary') return '次要授權組合';
  return slot || '—';
}

function quotaReason(quota, general, videoUploads) {
  const explicitReason = quota?.create_reason
    || quota?.can_start_reason
    || quota?.job_reason
    || quota?.reason
    || quota?.blocked_reason
    || general?.create_reason
    || general?.reason
    || videoUploads?.create_reason
    || videoUploads?.reason;
  if (explicitReason) return explicitReason;

  const generalAvailable = numericValue(general?.effective_available_units);
  const generalRequired = quotaMetric(quota, 'general', ['remaining_required', 'job_required', 'create_required'], numericValue(general?.projected_units, 0));
  if (generalAvailable !== null && generalRequired > generalAvailable) {
    return `General 配額不足：建立工作還需要 ${formatUnits(generalRequired)} 單位，目前可用 ${formatUnits(generalAvailable)} 單位。`;
  }

  const uploadAvailable = numericValue(videoUploads?.effective_available_units);
  const uploadRequired = quotaMetric(quota, 'video_uploads', ['remaining_required', 'job_required', 'create_required'], numericValue(videoUploads?.projected_units, 0));
  if (uploadAvailable !== null && uploadRequired > uploadAvailable) {
    return `Video Uploads 配額不足：需要 ${formatUnits(uploadRequired)} 單位，目前可用 ${formatUnits(uploadAvailable)} 單位。`;
  }
  return '後端尚未確認這份預覽可以建立背景工作。';
}

export function getYoutubeUploadQuotaDecision(preview) {
  const quota = preview?.quota || {};
  const general = quota.general || {};
  const videoUploads = quota.video_uploads || {};
  const uploadable = numericValue(preview?.summary?.uploadable, 0);
  const slot = preview?.youtube?.slot || preview?.youtube_slot || '';
  const snapshotSlot = preview?.preview_snapshot?.youtube_slot || '';
  const slotValid = Boolean(slot) && (!snapshotSlot || snapshotSlot === slot);
  const previewCanExecute = firstBoolean(
    preview?.preview_can_execute,
    preview?.preview_can_complete,
    preview?.preview?.can_execute,
    preview?.preview?.can_complete,
    quota.preview_can_execute,
    quota.preview_can_complete,
  ) ?? preview?.status === 'preview_ready';
  const explicitCreateCanExecute = firstBoolean(
    preview?.can_start,
    quota.can_start,
    preview?.create_can_execute,
    preview?.create_can_complete,
    preview?.create?.can_execute,
    preview?.create?.can_complete,
    quota.can_create,
    quota.create_can_execute,
    quota.create_can_complete,
  );
  const previewRead = {
    general: quotaMetric(quota, 'general', ['preview_read', 'preview_reads'], quotaMetric(quota, 'general', ['already_spent'], 0)),
    video_uploads: quotaMetric(quota, 'video_uploads', ['preview_read', 'preview_reads'], quotaMetric(quota, 'video_uploads', ['already_spent'], 0)),
  };
  const jobRequired = {
    general: quotaMetric(quota, 'general', ['remaining_required', 'job_required', 'create_required'], numericValue(general.projected_units, 0)),
    video_uploads: quotaMetric(quota, 'video_uploads', ['remaining_required', 'job_required', 'create_required'], numericValue(videoUploads.projected_units, 0)),
  };
  const total = {
    general: quotaMetric(quota, 'general', ['total', 'projected_full_workflow', 'projected_with_preview_reads'], previewRead.general + jobRequired.general),
    video_uploads: quotaMetric(quota, 'video_uploads', ['total', 'projected_full_workflow'], previewRead.video_uploads + jobRequired.video_uploads),
  };
  const generalRequired = numericValue(general.create_required_units, jobRequired.general);
  const uploadRequired = numericValue(videoUploads.create_required_units, jobRequired.video_uploads);
  const generalAvailable = numericValue(general.effective_available_units);
  const uploadAvailable = numericValue(videoUploads.effective_available_units);
  const bucketsFit = generalAvailable !== null && uploadAvailable !== null
    ? generalRequired <= generalAvailable && uploadRequired <= uploadAvailable
    : false;
  const reportedBucketsCanComplete = general.can_complete !== false && videoUploads.can_complete !== false;
  const canCreate = slotValid && (explicitCreateCanExecute ?? (
    previewCanExecute
    && quota.can_complete === true
    && reportedBucketsCanComplete
    && bucketsFit
  ));
  const confirmedExhausted = Boolean(
    quota.confirmed_by_google
      || quota.state === 'confirmed_exhausted'
      || general.confirmed_by_google
      || videoUploads.confirmed_by_google,
  );

  return {
    slot,
    snapshotSlot,
    slotValid,
    slotReason: preview?.youtube?.slot_reason || preview?.youtube?.reason || '',
    previewCanExecute,
    canCreate: Boolean(canCreate),
    canStart: Boolean(uploadable > 0 && canCreate),
    uploadable,
    confirmedExhausted,
    general,
    videoUploads,
    previewRead,
    jobRequired,
    total,
    estimated: quota.estimated_units || {},
    reason: !slotValid
      ? (slot ? `預覽 slot（${slot}）與 snapshot slot（${snapshotSlot || '未提供'}）不一致，無法安全建立工作。` : '後端未回傳實際 YouTube slot，無法安全建立工作。')
      : uploadable <= 0
      ? '沒有可上傳的項目。'
      : canCreate
        ? ''
        : `${quotaReason(quota, general, videoUploads)}${preview?.youtube?.slot_reason ? `（slot：${preview.youtube.slot_reason}）` : ''}`,
    resetAt: quota.reset_at || general.reset_at || videoUploads.reset_at || '',
    requiresCreateRecheck: previewCanExecute && explicitCreateCanExecute === undefined && quota.can_complete === true,
  };
}

function isRepreviewRequired(error) {
  return ['stale_preview', 'youtube_quota_no_available_slot', 'youtube_quota_exhausted', 'youtube_quota_safety_blocked'].includes(error?.code)
    || error?.status === 409
    || error?.status === 429;
}

export default function YouTubeUploadPage({ sysSettings = {}, authUser, mode = 'create', jobId, navigate }) {
  const toast = useToast();
  const location = useLocation();
  const isJobPage = mode === 'job';
  const [driveSource, setDriveSource] = useState('');
  const [preview, setPreview] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [jobAction, setJobAction] = useState(null);
  const [error, setError] = useState('');
  const [jobNotFound, setJobNotFound] = useState(false);
  const [recentJobId, setRecentJobId] = useState('');
  const [needsPreview, setNeedsPreview] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const driveScopeReady = authUser?.google_scopes?.drive_readonly !== false
    && authUser?.google_scopes?.drive_reauthorization_required !== true;
  const jobStorageKey = useMemo(() => {
    const accountKey = authUser?.sub || authUser?.email || '';
    return accountKey ? `creator-tools:youtube-upload-job:${accountKey}` : '';
  }, [authUser?.email, authUser?.sub]);
  const playlistId = preview?.playlist?.id || sysSettings.default_playlist_id || '';
  const quotaDecision = useMemo(() => getYoutubeUploadQuotaDecision(preview), [preview]);
  const canStart = Boolean(preview?.preview_token && preview?.preview_snapshot && quotaDecision.canStart && quotaDecision.previewCanExecute && !needsPreview);
  const jobActive = ACTIVE_JOB_STATUSES.has(job?.status);
  const currentItem = useMemo(() => {
    const index = job?.current_index;
    return index === null || index === undefined ? null : job?.items?.[index] || null;
  }, [job]);

  useEffect(() => {
    if (!jobStorageKey || typeof window === 'undefined') return undefined;
    let storedJobId = '';
    try {
      storedJobId = window.localStorage.getItem(jobStorageKey) || '';
    } catch {
      return undefined;
    }
    if (storedJobId) setRecentJobId(storedJobId);
    return undefined;
  }, [jobStorageKey]);

  useEffect(() => {
    if (!isJobPage || !jobId) return undefined;
    let cancelled = false;
    setLoading(true);
    setError('');
    setJobNotFound(false);
    api.getYoutubeDriveUploadJob(jobId)
      .then((storedJob) => {
        if (!cancelled) setJob(storedJob);
      })
      .catch((loadError) => {
        if (cancelled) return;
        if (loadError?.status === 404) {
          setJob(null);
          setJobNotFound(true);
          setError('工作不存在或不屬於目前帳號');
          return;
        }
        setError(errorText(loadError, '無法載入上傳工作狀態。'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [isJobPage, jobId]);

  useEffect(() => {
    if (!jobStorageKey || !job?.job_id || typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(jobStorageKey, job.job_id);
    } catch {
      // Ignore storage failures; the server remains the source of truth.
    }
  }, [job?.job_id, jobStorageKey]);

  useEffect(() => {
    if (!job?.job_id || !ACTIVE_JOB_STATUSES.has(job.status)) return undefined;
    let cancelled = false;
    let timer = null;
    let requestInFlight = false;

    const stopPolling = () => {
      if (timer === null) return;
      window.clearTimeout(timer);
      timer = null;
    };

    const schedulePoll = () => {
      if (cancelled || document.hidden || timer !== null) return;
      timer = window.setTimeout(() => {
        timer = null;
        poll();
      }, YOUTUBE_UPLOAD_POLL_INTERVAL_MS);
    };

    const poll = async () => {
      if (cancelled || document.hidden || requestInFlight) return;
      requestInFlight = true;
      let shouldContinue = true;
      try {
        const next = await api.getYoutubeDriveUploadJob(job.job_id);
        if (!cancelled) {
          setJob(next);
          if (!ACTIVE_JOB_STATUSES.has(next.status) && next.status === 'completed') toast.success('Drive 影片已全部上傳並加入共用 To-Post');
          shouldContinue = ACTIVE_JOB_STATUSES.has(next.status);
        }
      } catch (pollError) {
        if (!cancelled) setError(errorText(pollError, '無法更新上傳工作狀態。'));
      } finally {
        requestInFlight = false;
        if (shouldContinue) schedulePoll();
      }
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopPolling();
        return;
      }
      poll();
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    if (!document.hidden) poll();

    return () => {
      cancelled = true;
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [job?.job_id, job?.status, toast]);

  const reauthorizeDrive = async () => {
    try {
      saveOAuthReturnPath('google', `${location.pathname}${location.search}`);
      const response = await api.getAuthUrl();
      if (!response?.auth_url) throw new Error('無法取得 Google 授權網址。');
      window.location.href = response.auth_url;
    } catch (authError) {
      setError(errorText(authError, '無法建立 Google Drive 重新授權流程。'));
    }
  };

  const loadPreview = async (event) => {
    event?.preventDefault();
    if (!driveSource.trim() || loading || jobActive) return;
    setLoading(true);
    setError('');
    setNeedsPreview(false);
    setPreview(null);
    try {
      const response = await api.previewYoutubeDriveUpload(driveSource.trim());
      setPreview(response);
      toast.success(`已解析 ${response?.summary?.total || 0} 個 Drive 項目`);
    } catch (previewError) {
      setError(errorText(previewError, 'Drive 解析失敗。'));
    } finally {
      setLoading(false);
    }
  };

  const startJob = async () => {
    if (!canStart || loading || jobAction) return;
    setJobAction('start');
    setError('');
    try {
      const response = await api.createYoutubeDriveUploadJob({
        previewToken: preview.preview_token,
        previewSnapshot: preview.preview_snapshot,
      });
      if (response?.job_id && navigate) {
        try {
          window.localStorage.setItem(jobStorageKey, response.job_id);
        } catch {
          // The URL remains the source of truth when storage is unavailable.
        }
        navigate(PATHS.youtubeUploadJob(response.job_id));
        return;
      }
      setJob(response);
      toast.success(response.status === 'completed' ? '沒有新的影片需要上傳' : '上傳工作已建立，會在背景依序處理');
    } catch (startError) {
      if (isRepreviewRequired(startError)) {
        setPreview(null);
        setNeedsPreview(true);
      }
      setError(errorText(startError, '無法建立背景上傳工作。'));
    } finally {
      setJobAction(null);
    }
  };

  const cancelJob = async () => {
    if (!job?.job_id || jobAction) return;
    setConfirmCancel(false);
    setJobAction('cancel');
    try {
      setJob(await api.cancelYoutubeDriveUploadJob(job.job_id));
      toast.success('已要求停止尚未開始的影片');
    } catch (cancelError) {
      setError(errorText(cancelError, '取消上傳工作失敗。'));
    } finally {
      setJobAction(null);
    }
  };

  const retryJob = async () => {
    if (!job?.job_id || jobAction) return;
    setJobAction('retry');
    setError('');
    try {
      setJob(await api.retryYoutubeDriveUploadJob(job.job_id));
      toast.success('已重新排入失敗項目；已取得 YouTube ID 的項目只會重試加入 To-Post');
    } catch (retryError) {
      setError(errorText(retryError, '重試上傳工作失敗。'));
    } finally {
      setJobAction(null);
    }
  };

  return (
    <div className="page youtube-upload-page">
      <div className="page-header-row">
        <div className="page-header">
          <span className="eyebrow"><Upload size={15} /> YouTube 背景工作</span>
          <h1>上傳至 YouTube</h1>
          <p className="section-desc">從 Google Drive 依檔名自然排序逐部上傳；每部先設為 Private，再加入共用 To-Post 播放清單。</p>
        </div>
        <div className="page-actions">
          <Link className="btn btn-secondary" to={PATHS.youtubeConnections}><ListVideo size={16} /> YouTube 設定</Link>
        </div>
      </div>

      {isJobPage && <div className="page-actions"><Link className="btn btn-secondary" to={PATHS.youtubeUploadNew}><Upload size={16} /> 建立新的上傳工作</Link></div>}
      {!isJobPage && recentJobId && <div className="info-banner"><span>最近的背景工作仍可從 URL 繼續：</span><Link to={PATHS.youtubeUploadJob(recentJobId)}>開啟最近工作</Link></div>}

      {isJobPage && loading && <div className="loading-center">讀取中…</div>}
      {isJobPage && jobNotFound && <StatusMessage tone="error" title="找不到上傳工作"><span>工作不存在或不屬於目前帳號</span><Link className="btn btn-secondary status-message-action" to={PATHS.youtubeUploadNew}>返回建立上傳工作</Link></StatusMessage>}

      {!isJobPage && !driveScopeReady && (
        <StatusMessage tone="warning" title="尚未取得 Google Drive 權限" action={<button type="button" className="btn btn-secondary status-message-action" onClick={reauthorizeDrive}>重新授權 Google Drive</button>}>
          <span>目前登入 token 只有舊的 Google 權限；重新授權後才能讀取你貼上的 Drive ID／網址。</span>
        </StatusMessage>
      )}
      {error && !jobNotFound && <StatusMessage tone="error" title="上傳流程無法繼續"><span>{error}</span></StatusMessage>}
      {!isJobPage && needsPreview && <StatusMessage tone="warning" title="請重新預覽後再建立工作"><span>配額、slot 或 Drive 內容可能已變更；請重新解析 Drive 內容，確認後端最新的可執行狀態。</span></StatusMessage>}

      {!isJobPage && <form className="glass-panel card-padding card-stack" onSubmit={loadPreview}>
        <div>
          <h2 className="panel-title"><Upload size={19} /> Drive 來源</h2>
          <p className="panel-description">支援 Drive 資料夾 ID／網址、單一影片 ID／網址。第一版只讀取資料夾第一層。</p>
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="youtube-drive-source">Google Drive ID／網址</label>
          <SourceLinkInput id="youtube-drive-source" value={driveSource} onChange={(event) => setDriveSource(event.target.value)} sourceType="drive-item" placeholder="貼上 Drive 資料夾或影片 ID／網址" disabled={loading || jobActive} />
        </div>
        <div className="page-actions">
          <button className="btn btn-primary" type="submit" disabled={!driveSource.trim() || loading || jobActive || !driveScopeReady}>
            {loading ? <><Loader2 className="spin" size={17} />解析中…</> : <><RefreshCw size={17} />解析 Drive 內容</>}
          </button>
        </div>
      </form>}

      {!isJobPage && <section className="glass-panel card-padding card-stack">
        <div className="page-header-row">
          <div>
            <h2 className="panel-title"><ListVideo size={19} /> 共用 To-Post 播放清單</h2>
            <p className="panel-description">所有 YouTube 子頁面與這個上傳工作共用 YouTube 設定中的同一個播放清單。</p>
          </div>
          {playlistId && <a className="youtube-video-link" href={`https://www.youtube.com/playlist?list=${encodeURIComponent(playlistId)}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />開啟播放清單</a>}
        </div>
        <div className="upload-playlist-display">{playlistId || '尚未設定；請先到 YouTube 設定儲存共用 To-Post 播放清單。'}</div>
        {!playlistId && <Link className="btn btn-secondary settings-inline-button" to={PATHS.youtubeConnections}>前往 YouTube 設定</Link>}
      </section>
      }

      {!isJobPage && preview && (
        <section className="glass-panel card-padding card-stack">
          <div className="page-header-row">
            <div>
              <h2 className="panel-title"><CheckCircle2 size={19} /> 預覽結果</h2>
              <p className="panel-description">{preview.source?.name || preview.source?.id} ／ {preview.summary?.uploadable || 0} 個項目可上傳。</p>
            </div>
            <div className="upload-preview-routing">
              <span className="badge badge-connected">實際 slot：{youtubeSlotLabel(quotaDecision.slot)}</span>
              {quotaDecision.slot && <small>slot id：{quotaDecision.slot}</small>}
              {quotaDecision.slotReason && <small>{quotaDecision.slotReason}</small>}
            </div>
          </div>

          <div className="responsive-grid upload-quota-grid">
            <div className={`glass-panel upload-quota-card${quotaDecision.videoUploads.can_complete === false ? ' upload-quota-card-blocked' : ''}`}>
              <strong>Video Uploads</strong>
              <span>工作成本 {formatUnits(quotaDecision.jobRequired.video_uploads)} / {formatUnits(quotaDecision.videoUploads.limit || 100)}</span>
              <small>預覽讀取 {formatUnits(quotaDecision.previewRead.video_uploads)} · 完整流程 {formatUnits(quotaDecision.total.video_uploads)} · 可用 {quotaDecision.videoUploads.effective_available_units ?? '—'} 單位</small>
            </div>
            <div className={`glass-panel upload-quota-card${quotaDecision.general.can_complete === false ? ' upload-quota-card-blocked' : ''}`}>
              <strong>General</strong>
              <span>工作成本 {formatUnits(quotaDecision.jobRequired.general)} 單位</span>
              <small>預覽讀取 {formatUnits(quotaDecision.previewRead.general)} · 完整流程 {formatUnits(quotaDecision.total.general)} · 可用 {quotaDecision.general.effective_available_units ?? '—'} 單位</small>
            </div>
          </div>
          <div className="upload-quota-total">本次完整流程估算：General {formatUnits(quotaDecision.total.general ?? quotaDecision.estimated.general)} · Video Uploads {formatUnits(quotaDecision.total.video_uploads ?? quotaDecision.estimated.video_uploads)} · 合計 {formatUnits(quotaDecision.total.general + quotaDecision.total.video_uploads)} 單位</div>
          {quotaDecision.confirmedExhausted && <StatusMessage tone="error" title="Google 已確認配額耗盡"><span>目前 slot 已被 Google 確認配額已用完；官方重設{resetLabel(quotaDecision.resetAt) ? `（${resetLabel(quotaDecision.resetAt)}）` : ''}後，請重新解析 Drive 內容。</span></StatusMessage>}
          {!quotaDecision.confirmedExhausted && (!quotaDecision.previewCanExecute || !quotaDecision.canStart) && <StatusMessage tone="warning" title={quotaDecision.previewCanExecute ? '預覽已完成，但目前不可建立工作' : '預覽目前不可執行'}><span>{quotaDecision.reason} 請重新預覽以取得最新配額與 slot 判斷。</span></StatusMessage>}
          {quotaDecision.previewCanExecute && quotaDecision.canStart && <div className="upload-quota-ready">預覽已驗證，但建立前仍會重新檢查配額、slot 與 Drive 內容。</div>}

          <div className="upload-preview-table-wrap">
            <table className="upload-preview-table">
              <thead><tr><th scope="col">順序</th><th scope="col">檔名</th><th scope="col">大小</th><th scope="col">YouTube 標題</th><th scope="col">狀態</th></tr></thead>
              <tbody>{(preview.items || []).map((item) => <tr key={`${item.file_id}-${item.sequence}`}>
                <td>{item.upload_sequence || item.sequence}</td>
                <td><strong>{item.name || item.file_id}</strong><small>{item.file_id}</small></td>
                <td>{formatBytes(item.size)}</td>
                <td>{item.title || '—'}</td>
                <td><span className={`badge ${item.uploadable ? 'badge-connected' : 'badge-disconnected'}`}>{itemStatusLabel(item)}{item.skip_reason ? `：${item.skip_reason}` : ''}</span></td>
              </tr>)}</tbody>
            </table>
          </div>
          <div className="page-actions upload-actions">
            <button className="btn btn-success" type="button" onClick={startJob} disabled={!canStart || Boolean(jobAction) || jobActive}>
              {jobAction === 'start' ? <><Loader2 className="spin" size={17} />建立中…</> : <><Play size={17} />確認開始背景上傳</>}
            </button>
          </div>
        </section>
      )}

      {(isJobPage || job) && job && (
        <section className="glass-panel card-padding card-stack upload-job-panel">
          <div className="page-header-row">
            <div>
              <h2 className="panel-title"><Upload size={19} /> 上傳工作狀態</h2>
              <p className="panel-description">工作 ID：{job.job_id}</p>
            </div>
            <span className={`badge ${job.status === 'completed' ? 'badge-connected' : job.status === 'failed' ? 'badge-disconnected' : 'badge-warning'}`}>{jobStatusLabel(job.status)}</span>
          </div>
          <div className="upload-progress-copy"><strong>{job.progress?.completed || 0} / {job.progress?.total || job.items?.length || 0}</strong><span>{currentItem ? `目前：${currentItem.name}` : '目前沒有正在處理的影片'}</span></div>
          <div className="upload-progress-track"><span style={{ width: `${job.progress?.total ? Math.round(((job.progress?.completed || 0) / job.progress.total) * 100) : 0}%` }} /></div>
          {job.error?.message && <StatusMessage tone="warning" title="工作需要處理"><span>{job.error.message}</span></StatusMessage>}
          <div className="page-actions upload-actions">
            {jobActive && <button className="btn btn-secondary" type="button" onClick={() => setConfirmCancel(true)} disabled={Boolean(jobAction)}><Square size={16} />取消未開始項目</button>}
            {(job.status === 'failed' || job.status === 'paused') && <button className="btn btn-primary" type="button" onClick={retryJob} disabled={Boolean(jobAction)}>{jobAction === 'retry' ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}重試失敗項目</button>}
          </div>
          <div className="upload-job-results">{(job.items || []).map((item) => <div className="upload-job-result" key={`${item.drive_file_id}-${item.sequence}`}><span className="upload-job-result-index">{item.sequence}</span><div><strong>{item.name || item.drive_file_id}</strong>{item.youtube_video_id && <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(item.youtube_video_id)}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> YouTube</a>}</div><span className="badge">{itemStatusLabel(item)}</span></div>)}</div>
        </section>
      )}

      <ConfirmDialog open={confirmCancel} title="取消背景上傳？" message="已完成或已取得 YouTube ID 的影片不會刪除；只會停止尚未開始的項目。" confirmText="確認取消" cancelText="繼續上傳" variant="destructive" onConfirm={cancelJob} onCancel={() => setConfirmCancel(false)} />
    </div>
  );
}

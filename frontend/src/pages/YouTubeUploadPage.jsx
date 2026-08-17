import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ExternalLink, ListVideo, Loader2, Play, RefreshCw, Square, Upload } from 'lucide-react';
import { api } from '../services/api';
import SourceLinkInput from '../components/SourceLinkInput';
import { StatusMessage } from '../components/StatusMessage';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';

const ACTIVE_JOB_STATUSES = new Set(['queued', 'running', 'cancel_requested', 'paused']);

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

export default function YouTubeUploadPage({ sysSettings = {}, authUser, setActiveTab }) {
  const toast = useToast();
  const [driveSource, setDriveSource] = useState('');
  const [preview, setPreview] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [jobAction, setJobAction] = useState(null);
  const [error, setError] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);

  const driveScopeReady = authUser?.google_scopes?.drive_readonly !== false
    && authUser?.google_scopes?.drive_reauthorization_required !== true;
  const jobStorageKey = useMemo(() => {
    const accountKey = authUser?.sub || authUser?.email || '';
    return accountKey ? `creator-tools:youtube-upload-job:${accountKey}` : '';
  }, [authUser?.email, authUser?.sub]);
  const playlistId = preview?.playlist?.id || sysSettings.default_playlist_id || '';
  const canStart = Boolean(preview?.preview_token && preview?.preview_snapshot && preview?.summary?.uploadable > 0 && preview?.quota?.can_complete);
  const jobActive = ACTIVE_JOB_STATUSES.has(job?.status);
  const currentItem = useMemo(() => {
    const index = job?.current_index;
    return index === null || index === undefined ? null : job?.items?.[index] || null;
  }, [job]);

  useEffect(() => {
    if (!jobStorageKey || typeof window === 'undefined') return undefined;
    let cancelled = false;
    let storedJobId = '';
    try {
      storedJobId = window.localStorage.getItem(jobStorageKey) || '';
    } catch {
      return undefined;
    }
    if (!storedJobId) return undefined;

    api.getYoutubeDriveUploadJob(storedJobId)
      .then((storedJob) => {
        if (!cancelled) setJob(storedJob);
      })
      .catch((restoreError) => {
        if (cancelled || restoreError?.status !== 404) return;
        try {
          window.localStorage.removeItem(jobStorageKey);
        } catch {
          // Ignore storage failures; the server remains the source of truth.
        }
      });

    return () => {
      cancelled = true;
    };
  }, [jobStorageKey]);

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
    const poll = async () => {
      try {
        const next = await api.getYoutubeDriveUploadJob(job.job_id);
        if (!cancelled) {
          setJob(next);
          if (!ACTIVE_JOB_STATUSES.has(next.status) && next.status === 'completed') toast.success('Drive 影片已全部上傳並加入共用 To-Post');
        }
      } catch (pollError) {
        if (!cancelled) setError(errorText(pollError, '無法更新上傳工作狀態。'));
      }
    };
    poll();
    const timer = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.job_id, job?.status, toast]);

  const reauthorizeDrive = async () => {
    try {
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
      setJob(response);
      toast.success(response.status === 'completed' ? '沒有新的影片需要上傳' : '上傳工作已建立，會在背景依序處理');
    } catch (startError) {
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
          <button type="button" className="btn btn-secondary" onClick={() => setActiveTab?.('youtube_settings')}>
            <ListVideo size={16} /> YouTube 設定
          </button>
        </div>
      </div>

      {!driveScopeReady && (
        <StatusMessage tone="warning" title="尚未取得 Google Drive 權限" action={<button type="button" className="btn btn-secondary status-message-action" onClick={reauthorizeDrive}>重新授權 Google Drive</button>}>
          <span>目前登入 token 只有舊的 Google 權限；重新授權後才能讀取你貼上的 Drive ID／網址。</span>
        </StatusMessage>
      )}
      {error && <StatusMessage tone="error" title="上傳流程無法繼續"><span>{error}</span></StatusMessage>}

      <form className="glass-panel card-padding card-stack" onSubmit={loadPreview}>
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
      </form>

      <section className="glass-panel card-padding card-stack">
        <div className="page-header-row">
          <div>
            <h2 className="panel-title"><ListVideo size={19} /> 共用 To-Post 播放清單</h2>
            <p className="panel-description">所有 YouTube 子頁面與這個上傳工作共用 YouTube 設定中的同一個播放清單。</p>
          </div>
          {playlistId && <a className="youtube-video-link" href={`https://www.youtube.com/playlist?list=${encodeURIComponent(playlistId)}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />開啟播放清單</a>}
        </div>
        <div className="upload-playlist-display">{playlistId || '尚未設定；請先到 YouTube 設定儲存共用 To-Post 播放清單。'}</div>
        {setActiveTab && !playlistId && <button type="button" className="btn btn-secondary settings-inline-button" onClick={() => setActiveTab('youtube_settings')}>前往 YouTube 設定</button>}
      </section>

      {preview && (
        <section className="glass-panel card-padding card-stack">
          <div className="page-header-row">
            <div>
              <h2 className="panel-title"><CheckCircle2 size={19} /> 預覽結果</h2>
              <p className="panel-description">{preview.source?.name || preview.source?.id} ／ {preview.summary?.uploadable || 0} 個項目可上傳。</p>
            </div>
            <span className="badge badge-connected">slot：{preview.youtube?.slot || '—'}</span>
          </div>

          <div className="responsive-grid upload-quota-grid">
            <div className="glass-panel upload-quota-card"><strong>Video Uploads</strong><span>{preview.quota?.video_uploads?.projected_units || 0} / {preview.quota?.video_uploads?.limit || 100}</span><small>可用 {preview.quota?.video_uploads?.effective_available_units ?? '—'} units</small></div>
            <div className="glass-panel upload-quota-card"><strong>General</strong><span>{preview.quota?.general?.projected_with_preview_reads || 0} units</span><small>可用 {preview.quota?.general?.effective_available_units ?? '—'} units（含驗證讀取估算）</small></div>
          </div>
          {!preview.quota?.can_complete && <StatusMessage tone="warning" title="目前 quota 不足"><span>工作尚未建立；請等待 quota 重設，或使用仍有足夠雙 bucket 的 slot。</span></StatusMessage>}

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

      {job && (
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

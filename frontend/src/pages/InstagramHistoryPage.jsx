import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, History, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';

function formatDate(value) {
  if (!value) return '未提供';
  try {
    return new Intl.DateTimeFormat('zh-TW', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatPreflight(record) {
  const metadata = record.preflight || {};
  const dimensions = metadata.width && metadata.height ? `${metadata.width}×${metadata.height}` : '尺寸未提供';
  const duration = metadata.duration_seconds ? `${metadata.duration_seconds} 秒` : 'duration 未提供';
  return `${dimensions} · ${duration}`;
}

function recordKey(record) {
  return record.record_id || `${record.job_id}:${record.file_id}`;
}

const ACTIVE_TASK_STATUSES = new Set(['queued', 'running', 'cancel_requested']);

async function waitForTaskToFinish(taskId) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const current = await api.getTask(taskId);
    if (!ACTIVE_TASK_STATUSES.has(current.status)) return current;
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  return null;
}

export default function InstagramHistoryPage() {
  const toast = useToast();
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [confirmRecord, setConfirmRecord] = useState(null);
  const [confirmClearOpen, setConfirmClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deletingRecordId, setDeletingRecordId] = useState('');
  const [retryingRecordId, setRetryingRecordId] = useState('');

  const loadHistory = useCallback(async ({ showSpinner = true } = {}) => {
    if (showSpinner) setLoading(true);
    else setRefreshing(true);
    setErrorMessage('');
    try {
      const data = await api.getInstagramPublishHistory();
      setRecords(data.records || []);
    } catch (error) {
      setErrorMessage(error.message);
      toast.error(error.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const deleteRecord = async () => {
    if (!confirmRecord) return;
    const target = confirmRecord;
    const targetKey = recordKey(target);
    setConfirmRecord(null);
    setDeletingRecordId(targetKey);
    try {
      const result = await api.deleteInstagramPublishHistory(target.job_id, target.file_id);
      setRecords((current) => current.filter((record) => recordKey(record) !== targetKey));
      toast.success(
        result.drive_restored
          ? '歷史紀錄已刪除，影片已移回來源 Drive 資料夾，可重新上傳。'
          : '歷史紀錄已刪除，可重新讀取 Drive 影片並上傳。',
      );
    } catch (error) {
      toast.error(error.message);
    } finally {
      setDeletingRecordId('');
    }
  };

  const clearHistory = async () => {
    setConfirmClearOpen(false);
    setClearing(true);
    try {
      const result = await api.clearInstagramPublishHistory();
      await loadHistory({ showSpinner: false });
      if (result.failed_count > 0) {
        toast.warning(`已清除 ${result.deleted_count} 筆歷史紀錄，另有 ${result.failed_count} 筆未完成，請稍後重試。`);
      } else {
        toast.success(`已清除 ${result.deleted_count} 筆 Instagram 歷史紀錄。`);
      }
    } catch (error) {
      toast.error(error.message);
    } finally {
      setClearing(false);
    }
  };

  const retryRecord = async (record) => {
    const targetKey = recordKey(record);
    if (!record.task_id) {
      toast.error('找不到這筆歷史紀錄的影片任務，請重新整理後再試。');
      return;
    }
    setRetryingRecordId(targetKey);
    try {
      const queued = await api.retryTask(record.task_id);
      toast.info('已加入重試隊列；這次只會處理 Drive／R2 後續清理，不會重新發布 Instagram。');
      const queuedTask = queued.task || queued;
      const finished = ACTIVE_TASK_STATUSES.has(queuedTask.status)
        ? await waitForTaskToFinish(record.task_id)
        : queuedTask;
      await loadHistory({ showSpinner: false });
      if (!finished) {
        toast.warning('重試仍在處理中，請稍後刷新歷史紀錄。');
      } else if (finished.status === 'completed') {
        toast.success('後續清理完成，影片已移入 Published。');
      } else {
        toast.warning('重試完成但仍有後續清理問題，請查看發布工作結果。');
      }
    } catch (error) {
      toast.error(error.message);
    } finally {
      setRetryingRecordId('');
    }
  };

  if (loading) return <div className="loading-center">讀取 Instagram 歷史紀錄中...</div>;

  return <div className="section-gap" style={{ maxWidth: 1100 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
      <div>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}><History size={28} />Instagram 發布歷史紀錄</h1>
        <p className="section-desc">查看已發布的 Reels。刪除紀錄只會解除本機防重複鎖定，不會刪除 Instagram 上的貼文；若影片已移入 Published，刪除時會自動移回來源 Drive 資料夾。</p>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button className="btn btn-secondary" onClick={() => loadHistory({ showSpinner: false })} disabled={refreshing || clearing}><RefreshCw size={16} className={refreshing ? 'spin' : ''} />{refreshing ? '刷新中…' : '刷新紀錄'}</button><button className="btn btn-danger" onClick={() => setConfirmClearOpen(true)} disabled={!records.length || refreshing || clearing}><Trash2 size={16} />{clearing ? '清除中…' : '清除歷史'}</button></div>
    </div>

    {errorMessage && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{errorMessage}</span></div>}

    <div className="info-banner"><CheckCircle2 size={16} /><span>目前共 {records.length} 筆已發布紀錄。清除紀錄不會刪除 Instagram 貼文；若影片已移入 Published，系統會先移回來源 Drive 資料夾。</span></div>

    {!records.length ? <section className="glass-panel card-padding" style={{ display: 'grid', gap: 10, justifyItems: 'center', textAlign: 'center' }}>
      <History size={36} color="var(--text-muted)" />
      <h2>目前沒有發布紀錄</h2>
      <p className="section-desc">完成 Instagram Reels 發布後，紀錄會自動出現在這裡。</p>
    </section> : <div style={{ display: 'grid', gap: 14 }}>
      {records.map((record) => {
        const key = recordKey(record);
        const deleting = deletingRecordId === key;
        const retrying = retryingRecordId === key;
        const needsDriveRetry = Boolean(record.drive_move_error) || !record.drive_moved;
        return <article key={key} className="glass-panel" style={{ padding: 18, display: 'grid', gap: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ minWidth: 0 }}>
              <h2 style={{ color: '#fff', fontSize: '1.05rem', overflowWrap: 'anywhere' }}>{record.file_name || record.file_id || '未命名影片'}</h2>
              <p className="section-desc" style={{ marginTop: 5 }}>發布時間：{formatDate(record.published_at)} · {formatPreflight(record)}</p>
            </div>
            <span className={`badge ${needsDriveRetry ? 'badge-disconnected' : 'badge-connected'}`}><CheckCircle2 size={13} />{needsDriveRetry ? '已發布・待處理搬移' : '已發布'}</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10 }}>
            <div className="glass-panel" style={{ padding: 12 }}><span className="section-desc">人物／團體</span><p style={{ color: '#fff', marginTop: 4 }}>{record.person || '未提供'} · {record.team || '未提供'}</p></div>
            <div className="glass-panel" style={{ padding: 12 }}><span className="section-desc">Instagram Media ID</span><p style={{ color: '#fff', marginTop: 4, overflowWrap: 'anywhere' }}>{record.media_id || '未提供'}</p></div>
            <div className="glass-panel" style={{ padding: 12 }}><span className="section-desc">Drive File ID</span><p style={{ color: '#fff', marginTop: 4, overflowWrap: 'anywhere' }}>{record.file_id || '未提供'}</p></div>
            <div className="glass-panel" style={{ padding: 12 }}><span className="section-desc">Drive 狀態</span><p style={{ color: '#fff', marginTop: 4 }}>{record.drive_moved ? '已移入 Published' : '仍在來源資料夾'}</p></div>
          </div>
          {record.drive_move_error && <p style={{ color: '#fbbf24', overflowWrap: 'anywhere' }}>Published 移動錯誤：{record.drive_move_error}</p>}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <p className="section-desc" style={{ fontSize: '0.78rem' }}>{needsDriveRetry ? 'Instagram 已發布成功；可先重試後續搬移，避免產生重複貼文。' : '刪除後才能再次指定這支影片發布。'}</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {needsDriveRetry && <button className="btn btn-primary" onClick={() => retryRecord(record)} disabled={retrying || deleting}><RefreshCw size={16} className={retrying ? 'spin' : ''} />{retrying ? '重試中…' : '重試移入 Published'}</button>}
              <button className="btn btn-danger" onClick={() => setConfirmRecord(record)} disabled={deleting || retrying}><Trash2 size={16} />{deleting ? '刪除中…' : record.drive_moved ? '刪除紀錄並移回來源' : '刪除歷史紀錄'}</button>
            </div>
          </div>
        </article>;
      })}
    </div>}

    <ConfirmDialog
      open={confirmClearOpen}
      title="清除全部 Instagram 歷史紀錄？"
      message="將清除目前所有已發布紀錄；已移入 Published 的影片會先移回來源 Drive 資料夾。Instagram 上的貼文不會被刪除，若 Drive 搬移失敗，該筆紀錄會保留。"
      confirmText="清除歷史"
      cancelText="返回"
      variant="destructive"
      onConfirm={clearHistory}
      onCancel={() => setConfirmClearOpen(false)}
    />
    <ConfirmDialog
      open={Boolean(confirmRecord)}
      title="刪除 Instagram 歷史紀錄"
      message={confirmRecord?.drive_moved
        ? `確定刪除「${confirmRecord.file_name || confirmRecord.file_id}」的本機發布紀錄嗎？影片會從 Published 移回來源 Drive 資料夾，但 Instagram 上已發布的貼文不會被刪除。`
        : `確定刪除「${confirmRecord?.file_name || confirmRecord?.file_id}」的本機發布紀錄嗎？影片會留在來源 Drive 資料夾，但 Instagram 上已發布的貼文不會被刪除。`}
      confirmText="刪除紀錄"
      variant="destructive"
      onConfirm={deleteRecord}
      onCancel={() => setConfirmRecord(null)}
    />
  </div>;
}

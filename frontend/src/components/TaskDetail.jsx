import React, { useState } from 'react';
import { Ban, CheckCircle2, Loader2, RefreshCw } from 'lucide-react';
import ConfirmDialog from './ConfirmDialog';
import { isTaskRetryable, taskBadgeClass, taskOperationLabel, taskStatusLabel } from '../utils/taskStatus';

function cancelCopy(status) {
  if (status === 'queued') return '尚未開始，將立即從隊列移除。';
  if (status === 'running') return '會在下一個安全步驟停止，外部 API 無法強制中斷。';
  return '將不再等待重試。';
}

export default function TaskDetail({ task, onCancel, onRetry, busy = false, compact = false }) {
  const [cancelOpen, setCancelOpen] = useState(false);
  if (!task) return null;
  const canCancel = ['queued', 'running', 'paused'].includes(task.status);
  const cancelRequested = task.status === 'cancel_requested';
  const retryable = isTaskRetryable(task);
  return (
    <>
      <ConfirmDialog
        open={cancelOpen}
        title="取消這支影片任務？"
        message={`${cancelCopy(task.status)} 已完成的 Instagram／YouTube 外部操作不會回滾。`}
        confirmText="確認取消"
        cancelText="返回"
        variant="destructive"
        onConfirm={() => { setCancelOpen(false); onCancel?.(task); }}
        onCancel={() => setCancelOpen(false)}
      />
      <div className={`task-detail ${compact ? 'task-detail-compact' : ''}`}>
        <div className="task-detail-main">
          {task.thumbnail_url && <img className="task-thumbnail" src={task.thumbnail_url} alt="" />}
          <div className="task-detail-copy">
            <strong>{task.video_title || task.video_id || '未命名影片'}</strong>
            <span>{task.platform === 'instagram' ? 'Instagram' : 'YouTube'} · {taskOperationLabel(task.operation)}</span>
            <span className="task-detail-id">Video／Drive ID：{task.video_id || '—'} · Batch：{task.batch_short_code || task.batch_id?.slice(0, 8)}</span>
          </div>
        </div>
        <div className="task-detail-status">
          <span className={`badge ${taskBadgeClass(task.status)}`}>
            {task.status === 'running' && <Loader2 size={12} className="spin" />}
            {taskStatusLabel(task.status)}
          </span>
          <span className="task-progress-label">{task.stage_label || task.stage} · {Math.round(task.progress_percent || 0)}%</span>
          {task.status === 'cancel_requested' && <span className="task-cancel-note">正在取消</span>}
          {task.cancel_too_late && <span className="task-cancel-note">取消要求太晚，操作已完成</span>}
          {task.error && <span className="task-error-text">{task.error}</span>}
        </div>
        <div className="task-detail-actions">
          {retryable && <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => onRetry?.(task)}><RefreshCw size={14} />重試</button>}
          {(canCancel || cancelRequested) && <button className="btn btn-danger" type="button" disabled={busy || cancelRequested} onClick={() => setCancelOpen(true)}><Ban size={14} />{cancelRequested ? '取消中…' : '取消'}</button>}
          {task.status === 'succeeded' && <span className="task-success-note"><CheckCircle2 size={14} />外部操作已完成</span>}
        </div>
      </div>
    </>
  );
}

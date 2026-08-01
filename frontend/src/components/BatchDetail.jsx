import React, { useState } from 'react';
import { Ban, Layers, RefreshCw } from 'lucide-react';
import ConfirmDialog from './ConfirmDialog';
import TaskDetail from './TaskDetail';
import { isTaskRetryable, taskStatusLabel } from '../utils/taskStatus';

export default function BatchDetail({ batch, onCancel, onRetry, onTaskCancel, onTaskRetry, busy = false }) {
  const [cancelOpen, setCancelOpen] = useState(false);
  const tasks = batch?.tasks || [];
  const unfinished = tasks.filter((task) => !['failed', 'skipped', 'succeeded', 'succeeded_with_warnings', 'canceled', 'canceled_with_warnings'].includes(task.status));
  const retryable = tasks.some(isTaskRetryable);
  if (!batch) return null;
  return (
    <section className="glass-panel batch-detail-panel">
      <ConfirmDialog
        open={cancelOpen}
        title="取消此批次未完成任務？"
        message={`將取消 ${unfinished.length} 支影片，其中 ${unfinished.filter((task) => task.status === 'running').length} 支正在執行；已完成影片不受影響，外部操作不會回滾。`}
        confirmText="取消批次未完成任務"
        cancelText="返回"
        variant="destructive"
        onConfirm={() => { setCancelOpen(false); onCancel?.(batch); }}
        onCancel={() => setCancelOpen(false)}
      />
      <div className="batch-detail-header">
        <div><h2><Layers size={19} />批次 {batch.batch_short_code || batch.id?.slice(0, 8)}</h2><p>{batch.platform} · {taskStatusLabel(batch.status)} · 共 {tasks.length} 支</p></div>
        <div className="task-detail-actions">
          {retryable && <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => onRetry?.(batch)}><RefreshCw size={14} />重試未完成</button>}
          {unfinished.length > 0 && <button className="btn btn-danger" type="button" disabled={busy} onClick={() => setCancelOpen(true)}><Ban size={14} />取消此批次未完成任務</button>}
        </div>
      </div>
      <div className="batch-detail-tasks">
        {tasks.map((task) => <TaskDetail key={task.id} task={task} compact busy={busy} onCancel={onTaskCancel} onRetry={onTaskRetry} />)}
      </div>
    </section>
  );
}

import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Filter, ListTodo, RefreshCw, Trash2 } from 'lucide-react';
import ConfirmDialog from '../components/ConfirmDialog';
import TaskDetail from '../components/TaskDetail';
import { useActivityCenter } from '../hooks/useActivityCenter';
import {
  TASK_ACTIVE_STATUSES,
  TASK_NEEDS_ATTENTION,
  TASK_UNFINISHED_QUEUE_STATUSES,
  taskBadgeClass,
  taskOperationLabel,
  taskStageLabel,
  taskStatusLabel,
} from '../utils/taskStatus';

const filters = [
  ['unfinished', '未完成隊列'],
  ['all', '全部'],
  ['active', '執行中'],
  ['queued', '排隊中'],
  ['cancel_requested', '正在取消'],
  ['attention', '需要處理'],
  ['completed', '已完成'],
  ['canceled', '已取消'],
];

function isCompleted(task) {
  return ['succeeded', 'succeeded_with_warnings', 'skipped'].includes(task.status);
}

function isCanceled(task) {
  return ['canceled', 'canceled_with_warnings'].includes(task.status);
}

function taskOrderValue(value) {
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

function taskSequenceValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

function compareTaskSubmissionOrder(left, right) {
  const createdOrder = taskOrderValue(left.created_at) - taskOrderValue(right.created_at);
  if (createdOrder) return createdOrder;
  const queueOrder = taskSequenceValue(left.queue_sequence) - taskSequenceValue(right.queue_sequence);
  if (queueOrder) return queueOrder;
  return String(left.id || '').localeCompare(String(right.id || ''));
}

export default function TaskQueuePage({ selectedTaskId }) {
  const {
    tasks, summary, loading, refreshing, error, refresh, cancelTask, retryTask, clearQueue, showToast,
  } = useActivityCenter();
  const [filter, setFilter] = useState('unfinished');
  const [platform, setPlatform] = useState('all');
  const [operation, setOperation] = useState('all');
  const [clearQueueOpen, setClearQueueOpen] = useState(false);
  const [busyId, setBusyId] = useState(null);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!selectedTaskId) return;
    const element = document.getElementById(`task-${selectedTaskId}`);
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element?.classList.add('task-row-focused');
    const timer = window.setTimeout(() => element?.classList.remove('task-row-focused'), 1800);
    return () => window.clearTimeout(timer);
  }, [selectedTaskId, tasks]);

  const orderedTasks = useMemo(() => [...tasks].sort(compareTaskSubmissionOrder), [tasks]);
  const operationOptions = useMemo(() => [...new Set(orderedTasks.map((task) => task.operation).filter(Boolean))], [orderedTasks]);
  const filteredTasks = useMemo(() => orderedTasks.filter((task) => {
    if (platform !== 'all' && task.platform !== platform) return false;
    if (operation !== 'all' && task.operation !== operation) return false;
    if (filter === 'unfinished' && !TASK_UNFINISHED_QUEUE_STATUSES.includes(task.status)) return false;
    if (filter === 'active' && !TASK_ACTIVE_STATUSES.includes(task.status)) return false;
    if (filter === 'queued' && task.status !== 'queued') return false;
    if (filter === 'cancel_requested' && task.status !== 'cancel_requested') return false;
    if (filter === 'attention' && !TASK_NEEDS_ATTENTION.includes(task.status)) return false;
    if (filter === 'completed' && !isCompleted(task)) return false;
    if (filter === 'canceled' && !isCanceled(task)) return false;
    return true;
  }), [filter, operation, platform, orderedTasks]);

  const activeTasks = tasks.filter((task) => TASK_ACTIVE_STATUSES.includes(task.status));
  const runningCount = activeTasks.filter((task) => task.status === 'running').length;
  const unfinishedTasks = tasks.filter((task) => ['queued', 'running', 'cancel_requested', 'paused'].includes(task.status));
  const queuedPausedCount = tasks.filter((task) => ['queued', 'paused'].includes(task.status)).length;
  const instagramCount = unfinishedTasks.filter((task) => task.platform === 'instagram').length;
  const youtubeCount = unfinishedTasks.filter((task) => task.platform === 'youtube').length;

  const execute = async (action, id) => {
    setBusyId(id);
    try { return await action(); } catch (actionError) { showToast?.('error', actionError.message); return null; }
    finally { setBusyId(null); }
  };

  const renderTask = (task) => (
    <div className="task-row" id={`task-${task.id}`} key={task.id}>
      <div className="task-row-platform"><span className={`platform-dot platform-${task.platform}`} />{task.platform === 'instagram' ? 'Instagram' : 'YouTube'}</div>
      <div className="task-row-video"><strong>{task.video_title || task.video_id || '未命名影片'}</strong><span>{task.video_id || '—'}</span></div>
      <div className="task-row-operation">{taskOperationLabel(task.operation)}</div>
      <div className="task-row-status"><span className={`badge ${task.stage === 'waiting_youtube_quota' ? 'badge-warning' : taskBadgeClass(task.status)}`}>{task.stage === 'waiting_youtube_quota' ? '等待 YouTube 配額' : taskStatusLabel(task.status)}</span><small>{task.queue_position ? `Lane 第 ${task.queue_position} 位` : '—'}</small></div>
      <div className="task-row-progress"><span>{taskStageLabel(task.stage, task.stage_label)}</span><div className="task-progress-track"><span style={{ width: `${Math.min(Math.max(task.progress_percent || 0, 0), 100)}%` }} /></div><small>{Math.round(task.progress_percent || 0)}%</small>{task.next_attempt_at && task.status === 'queued' && <small>自動重試：{new Date(task.next_attempt_at).toLocaleString()}</small>}</div>
      <div className="task-row-time"><span>建立：{task.created_at ? new Date(task.created_at).toLocaleString() : '—'}</span><span>更新：{task.updated_at ? new Date(task.updated_at).toLocaleString() : '—'}</span></div>
      <TaskDetail task={task} compact busy={busyId === task.id} onCancel={() => execute(() => cancelTask(task.id), task.id)} onRetry={() => execute(() => retryTask(task.id), task.id)} />
    </div>
  );

  return (
    <div className="section-gap task-queue-page">
      <ConfirmDialog
        open={clearQueueOpen}
        title="清空任務隊列？"
        message={`Instagram 未完成 ${instagramCount} 支、YouTube 未完成 ${youtubeCount} 支；正在執行 ${runningCount} 支，排隊／暫停 ${queuedPausedCount} 支。清空只會取消未完成任務，不會刪除歷史紀錄；已完成的外部操作不會被回滾。`}
        confirmText="清空任務隊列"
        cancelText="返回"
        variant="destructive"
        onConfirm={() => { setClearQueueOpen(false); execute(clearQueue, 'queue'); }}
        onCancel={() => setClearQueueOpen(false)}
      />
      <div className="task-queue-header">
        <div><div className="section-header"><ListTodo size={24} color="var(--primary)" /><h1>任務隊列</h1></div><p className="section-desc">依送出順序由最早到最晚顯示；每支影片任務可獨立取消或重試。</p></div>
        <div className="task-queue-header-actions"><button className="btn btn-secondary" type="button" onClick={() => refresh()} disabled={refreshing}><RefreshCw size={15} className={refreshing ? 'spin' : ''} />重新整理</button><button className="btn btn-danger" type="button" disabled={!unfinishedTasks.length || busyId === 'queue'} onClick={() => setClearQueueOpen(true)}><Trash2 size={15} />清空任務隊列</button></div>
      </div>
      <div className="task-summary-strip"><span>未完成 <strong>{summary?.tasks?.active ?? activeTasks.length}</strong></span><span>需要處理 <strong>{(summary?.tasks?.paused || 0) + (summary?.tasks?.failed || 0)}</strong></span><span>已完成 <strong>{summary?.tasks?.completed || 0}</strong></span><span>通知未讀 <strong>{summary?.unread_notification_count || 0}</strong></span></div>
      <div className="task-filter-bar">
        <Filter size={16} />
        <div className="task-filter-pills">{filters.map(([value, label]) => <button key={value} type="button" className={`filter-pill ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{label}</button>)}</div>
        <select className="form-select" value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="all">全部平台</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option></select>
        <select className="form-select" value={operation} onChange={(event) => setOperation(event.target.value)}><option value="all">各 operation</option>{operationOptions.map((item) => <option key={item} value={item}>{taskOperationLabel(item)}</option>)}</select>
      </div>
      {error && <div className="error-alert"><AlertTriangle size={18} />{error}<button className="btn btn-secondary" type="button" onClick={() => refresh()}>重試</button></div>}
      {loading && !tasks.length ? <div className="loading-center">正在載入任務隊列…</div> : !filteredTasks.length ? <div className="glass-panel task-empty"><ListTodo size={28} /><strong>目前沒有符合篩選的影片任務</strong><span>新的 Instagram／YouTube 工作會在這裡持久保存。</span></div> : (
        <div className="task-list">
          <div className="task-list-heading"><span>平台</span><span>影片／ID</span><span>操作</span><span>狀態</span><span>階段／進度</span><span>建立／更新</span><span>操作</span></div>
          {filteredTasks.map(renderTask)}
        </div>
      )}
    </div>
  );
}

export const TASK_STATUS_LABELS = {
  queued: '排隊中',
  running: '執行中',
  cancel_requested: '正在取消',
  paused: '需要處理',
  failed: '失敗',
  skipped: '已略過',
  succeeded: '已完成',
  succeeded_with_warnings: '已完成但有警告',
  canceled: '已取消',
  canceled_with_warnings: '已取消但清理有警告',
  partially_canceled: '部分取消',
};

export const TASK_OPERATION_LABELS = {
  'instagram.reels_publish': 'Instagram Reels 發布',
  'youtube.metadata_update': 'YouTube 標題／描述更新',
  'youtube.publish_cleanup': 'YouTube 公開並移出 To-Post',
};

export const TASK_STAGE_LABELS = {
  waiting_youtube_quota: '等待 YouTube 配額重設',
  waiting_rate_limit: '等待 Meta 限流解除',
};

export const TASK_ACTIVE_STATUSES = ['queued', 'running', 'cancel_requested'];
export const TASK_UNFINISHED_QUEUE_STATUSES = ['queued', 'running', 'cancel_requested', 'paused'];
export const TASK_NEEDS_ATTENTION = ['paused', 'failed', 'succeeded_with_warnings', 'canceled_with_warnings'];

export function taskStatusLabel(status) {
  return TASK_STATUS_LABELS[status] || status || '未知';
}

export function taskOperationLabel(operation) {
  return TASK_OPERATION_LABELS[operation] || operation || '未知操作';
}

export function taskBadgeClass(status) {
  if (['failed', 'canceled_with_warnings'].includes(status)) return 'badge-disconnected';
  if (['succeeded', 'skipped'].includes(status)) return 'badge-connected';
  if (['paused', 'succeeded_with_warnings'].includes(status)) return 'badge-warning';
  return 'badge-info';
}

export function taskStageLabel(stage, fallback = '') {
  return TASK_STAGE_LABELS[stage] || fallback || stage || '未知階段';
}

export function isTaskActive(task) {
  return TASK_ACTIVE_STATUSES.includes(task?.status);
}

export function isTaskRetryable(task) {
  return Boolean(task?.retryable && ['failed', 'paused', 'canceled', 'canceled_with_warnings', 'succeeded_with_warnings'].includes(task?.status));
}

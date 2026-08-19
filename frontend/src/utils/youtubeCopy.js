export const YOUTUBE_COPY = Object.freeze({
  featureName: '發布草稿',
  pageTitle: '發布 YouTube 草稿',
  setPublic: '設為公開',
  removeFromToPost: '移出 To-Post 播放清單',
  publishConfirmAction: '設為公開並移出清單',
  updateMetadata: '更新標題與描述',
  batchUpdate: '批次更新',
  readLoading: '讀取中…',
  updateLoading: '更新中…',
});

export function formatCount(value) {
  const count = Number(value);
  return Number.isFinite(count) ? count.toLocaleString() : '0';
}

export function formatVideoCount(value) {
  return `${formatCount(value)} 支影片`;
}

export function formatVideoId(value) {
  return `影片 ID：${value || '未提供'}`;
}

export function formatQuotaUnits(value) {
  return `${formatCount(value)} 單位`;
}

export function formatVideoUploadTime(value) {
  if (!value) return '未提供（排在最後）';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '未提供（排在最後）' : date.toLocaleString();
}

export function formatResultCounts(result = {}, { includeWarning = false } = {}) {
  const counts = [
    `成功 ${formatVideoCount(result.succeeded_count || 0)}`,
    ...(includeWarning ? [`警告 ${formatVideoCount(result.warning_count || 0)}`] : []),
    `略過 ${formatVideoCount(result.skipped_count || 0)}`,
    `失敗 ${formatVideoCount(result.failed_count || 0)}`,
    `未執行 ${formatVideoCount(result.not_attempted_count || 0)}`,
  ];
  return counts.join('、');
}

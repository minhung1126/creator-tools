import React from 'react';

export const RESULT_STATUS = {
  succeeded: { label: '成功', tone: 'success' },
  succeeded_with_warnings: { label: '完成但需處理', tone: 'warning' },
  skipped: { label: '略過', tone: 'neutral' },
  failed: { label: '失敗', tone: 'error' },
  not_attempted: { label: '未執行', tone: 'neutral' },
};

export function getResultStatus(status) {
  return RESULT_STATUS[status] || RESULT_STATUS.not_attempted;
}

export default function ResultStatus({ status, compact = false }) {
  const result = getResultStatus(status);
  return <span className={`result-status result-status-${result.tone}${compact ? ' result-status-compact' : ''}`}>{result.label}</span>;
}


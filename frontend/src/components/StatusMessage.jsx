import React from 'react';
import ResultStatus from './ResultStatus';

const ROLE_BY_TONE = {
  error: 'alert',
  warning: 'status',
  info: 'status',
  success: 'status',
};

export function StatusMessage({
  tone = 'info',
  title,
  children,
  action,
  status,
  className = '',
}) {
  const resolvedTone = status === 'failed' ? 'error' : tone;
  return (
    <div className={`status-message status-message-${resolvedTone} ${className}`.trim()} role={ROLE_BY_TONE[resolvedTone] || 'status'}>
      <div className="status-message-content">
        {status && <ResultStatus status={status} compact />}
        {title && <strong>{title}</strong>}
        {children && <span>{children}</span>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ title, children, action, className = '' }) {
  return (
    <div className={`empty-state ${className}`.trim()} role="status">
      {title && <strong>{title}</strong>}
      {children && <span>{children}</span>}
      {action}
    </div>
  );
}


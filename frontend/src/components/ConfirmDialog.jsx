import React from 'react';
import { AlertTriangle } from 'lucide-react';

export default function ConfirmDialog({ open, title, message, confirmText, cancelText, onConfirm, onCancel, variant }) {
  if (!open) return null;

  const isDestructive = variant === 'destructive';

  return (
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="confirm-header">
          <AlertTriangle size={22} color={isDestructive ? '#f87171' : 'var(--primary)'} />
          <h3 className="confirm-title">{title || '確認操作'}</h3>
        </div>
        <p className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button className="btn btn-secondary" onClick={onCancel}>
            {cancelText || '取消'}
          </button>
          <button
            className={`btn ${isDestructive ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
          >
            {confirmText || '確認'}
          </button>
        </div>
      </div>
    </div>
  );
}

import React, { useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';

export default function ConfirmDialog({ open, title, message, confirmText, cancelText, onConfirm, onCancel, variant }) {
  const cancelRef = useRef(null);
  const dialogRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const previousActive = document.activeElement;
    cancelRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancel?.();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previousActive instanceof HTMLElement) previousActive.focus();
    };
  }, [onCancel, open]);
  if (!open) return null;

  const isDestructive = variant === 'destructive';

  return (
    <div className="confirm-overlay" role="presentation" onClick={onCancel}>
      <div ref={dialogRef} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-message" onClick={(e) => e.stopPropagation()}>
        <div className="confirm-header">
          <AlertTriangle size={22} color={isDestructive ? '#f87171' : 'var(--primary)'} />
          <h3 id="confirm-dialog-title" className="confirm-title">{title || '確認操作'}</h3>
        </div>
        <p id="confirm-dialog-message" className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="btn btn-secondary" onClick={onCancel}>
            {cancelText || '取消'}
          </button>
          <button
            type="button"
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

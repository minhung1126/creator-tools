import React, { useRef, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import Dialog from './Dialog';

export default function ConfirmDialog({ open, title, message, confirmText, cancelText, onConfirm, onCancel, variant, busy = false }) {
  const cancelRef = useRef(null);
  const submittingRef = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  if (!open) return null;

  const isDestructive = variant === 'destructive';
  const isBusy = busy || submitting;
  const handleConfirm = async () => {
    if (isBusy || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      await onConfirm?.();
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      className={`confirm-dialog${isDestructive ? ' confirm-dialog-destructive' : ''}`}
      overlayClassName="confirm-overlay"
      titleId="confirm-dialog-title"
      descriptionId="confirm-dialog-message"
      initialFocusRef={cancelRef}
      onEscape={onCancel}
      onBackdropClick={onCancel}
      busy={isBusy}
    >
        <div className="confirm-header">
          <AlertTriangle size={22} aria-hidden="true" />
          <h3 id="confirm-dialog-title" className="confirm-title">{title || '確認操作'}</h3>
        </div>
        <p id="confirm-dialog-message" className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="btn btn-secondary" onClick={onCancel} disabled={isBusy}>
            {cancelText || '取消'}
          </button>
          <button
            type="button"
            className={`btn ${isDestructive ? 'btn-danger' : 'btn-primary'}`}
            onClick={handleConfirm}
            disabled={isBusy}
          >
            {isBusy && <RefreshCw size={15} className="spin" aria-hidden="true" />}
            {isBusy ? '處理中…' : (confirmText || '確認')}
          </button>
        </div>
    </Dialog>
  );
}

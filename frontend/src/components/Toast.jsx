import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from 'lucide-react';

const ToastContext = createContext(null);
const ICONS = { success: CheckCircle2, error: XCircle, warning: AlertTriangle, info: Info };

function ToastItem({ toast, onRemove }) {
  const [exiting, setExiting] = useState(false);
  const Icon = ICONS[toast.type] || Info;

  useEffect(() => {
    const timer = setTimeout(() => {
      setExiting(true);
      setTimeout(() => onRemove(toast.id), 300);
    }, toast.duration || 4000);
    return () => clearTimeout(timer);
  }, [toast, onRemove]);

  const close = () => {
    setExiting(true);
    setTimeout(() => onRemove(toast.id), 300);
  };

  return (
    <div className={`toast-item toast-${toast.type} ${exiting ? 'toast-exit' : ''}`}>
      <Icon size={18} />
      <span className="toast-message">{toast.message}</span>
      <button type="button" className="toast-close" aria-label="關閉通知" onClick={close}>
        <X size={14} />
      </button>
    </div>
  );
}

function OperationProgressItem({ operation, onRemove }) {
  const isRunning = operation.status === 'running';
  const Icon = isRunning ? Loader2 : operation.status === 'error' ? XCircle : CheckCircle2;
  const total = Math.max(Number(operation.total) || 0, 0);
  const completed = Math.min(Math.max(Number(operation.completed) || 0, 0), total || Number.MAX_SAFE_INTEGER);
  const percent = Math.min(Math.max(Number(operation.percent) || 0, 0), 100);
  const statusLabel = isRunning ? '處理中' : operation.status === 'error' ? '需要處理' : '已完成';

  return (
    <div className={`operation-item operation-${operation.status}`} role="status" aria-live="polite">
      <div className="operation-header">
        <Icon size={18} className={isRunning ? 'spin' : undefined} />
        <div className="operation-heading">
          <strong>{operation.title || '背景工作'}</strong>
          <span>{statusLabel}</span>
        </div>
        <button type="button" className="toast-close" aria-label="關閉進度通知" onClick={() => onRemove(operation.id)}>
          <X size={14} />
        </button>
      </div>
      <p className="operation-message">{operation.message || '正在準備…'}</p>
      <div className="operation-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="operation-meta">
        <span>{total ? `${completed} / ${total} 支完成` : '正在建立任務…'}</span>
        <span>{Math.round(percent)}%</span>
      </div>
    </div>
  );
}

let toastIdCounter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const [operations, setOperations] = useState([]);
  const operationsRef = useRef(operations);
  operationsRef.current = operations;

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const notification = {
      id: `${Date.now()}-${++toastIdCounter}`,
      message: String(message),
      type: ICONS[type] ? type : 'info',
      duration,
    };
    setToasts((prev) => [...prev, notification]);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const startOperation = useCallback((operation) => {
    const next = {
      status: 'running',
      total: 0,
      completed: 0,
      percent: 0,
      ...operation,
    };
    setOperations((prev) => [...prev.filter((item) => item.id !== next.id), next]);
  }, []);

  const updateOperation = useCallback((id, patch) => {
    setOperations((prev) => prev.map((operation) => (
      operation.id === id ? { ...operation, ...patch } : operation
    )));
  }, []);

  const finishOperation = useCallback((id, patch = {}) => {
    setOperations((prev) => prev.map((operation) => (
      operation.id === id
        ? { ...operation, ...patch, status: patch.status || 'success' }
        : operation
    )));
  }, []);

  const removeOperation = useCallback((id) => {
    setOperations((prev) => prev.filter((operation) => operation.id !== id));
  }, []);

  useEffect(() => {
    const poll = async () => {
      const pollable = operationsRef.current.filter(
        (operation) => operation.status === 'running' && typeof operation.poll === 'function',
      );
      await Promise.all(pollable.map(async (operation) => {
        try {
          const patch = await operation.poll();
          if (patch) updateOperation(operation.id, patch);
        } catch {
          // Keep the last known progress; the next interval retries quietly.
        }
      }));
    };
    const timer = window.setInterval(poll, 1500);
    return () => window.clearInterval(timer);
  }, [updateOperation]);

  const toast = useMemo(() => ({
    success: (message, duration) => addToast(message, 'success', duration),
    error: (message, duration) => addToast(message, 'error', duration || 6000),
    warning: (message, duration) => addToast(message, 'warning', duration),
    info: (message, duration) => addToast(message, 'info', duration),
    startOperation,
    updateOperation,
    finishOperation,
    removeOperation,
  }), [addToast, finishOperation, removeOperation, startOperation, updateOperation]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-container">
        {operations.map((item) => <OperationProgressItem key={item.id} operation={item} onRemove={removeOperation} />)}
        {toasts.map((item) => <ToastItem key={item.id} toast={item} onRemove={removeToast} />)}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}

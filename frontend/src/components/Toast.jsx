import React, { useState, useEffect, useCallback, createContext, useContext, useMemo } from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from 'lucide-react';

const ToastContext = createContext(null);
const NOTIFICATION_STORAGE_KEY = 'creator-tools.notifications.v1';
const MAX_NOTIFICATIONS = 100;

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

function loadStoredNotifications() {
  if (typeof window === 'undefined') return [];

  try {
    const stored = JSON.parse(window.localStorage.getItem(NOTIFICATION_STORAGE_KEY) || '[]');
    if (!Array.isArray(stored)) return [];

    return stored
      .filter((item) => item && item.id && typeof item.message === 'string')
      .slice(0, MAX_NOTIFICATIONS)
      .map((item) => ({
        id: item.id,
        message: item.message,
        type: ICONS[item.type] ? item.type : 'info',
        createdAt: item.createdAt || new Date().toISOString(),
        read: Boolean(item.read),
      }));
  } catch (error) {
    console.warn('Failed to load notification history:', error);
    return [];
  }
}

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

  return (
    <div className={`toast-item toast-${toast.type} ${exiting ? 'toast-exit' : ''}`}>
      <Icon size={18} />
      <span className="toast-message">{toast.message}</span>
      <button
        type="button"
        className="toast-close"
        aria-label="關閉通知"
        onClick={() => {
          setExiting(true);
          setTimeout(() => onRemove(toast.id), 300);
        }}
      >
        <X size={14} />
      </button>
    </div>
  );
}

let toastIdCounter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const [notifications, setNotifications] = useState(loadStoredNotifications);

  useEffect(() => {
    try {
      window.localStorage.setItem(NOTIFICATION_STORAGE_KEY, JSON.stringify(notifications));
    } catch (error) {
      console.warn('Failed to save notification history:', error);
    }
  }, [notifications]);

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const normalizedType = ICONS[type] ? type : 'info';
    const notification = {
      id: `${Date.now()}-${++toastIdCounter}`,
      message: String(message),
      type: normalizedType,
      createdAt: new Date().toISOString(),
      read: false,
    };

    setToasts((prev) => [...prev, { ...notification, duration }]);
    setNotifications((prev) => [notification, ...prev].slice(0, MAX_NOTIFICATIONS));
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((notification) => (
      notification.read ? notification : { ...notification, read: true }
    )));
  }, []);

  const markNotificationRead = useCallback((id) => {
    setNotifications((prev) => prev.map((notification) => (
      notification.id === id ? { ...notification, read: true } : notification
    )));
  }, []);

  const clearNotifications = useCallback(() => {
    setNotifications([]);
  }, []);

  const unreadCount = notifications.reduce((count, notification) => (
    count + (notification.read ? 0 : 1)
  ), 0);

  const toast = useMemo(() => ({
    success: (msg, dur) => addToast(msg, 'success', dur),
    error: (msg, dur) => addToast(msg, 'error', dur || 6000),
    warning: (msg, dur) => addToast(msg, 'warning', dur),
    info: (msg, dur) => addToast(msg, 'info', dur),
    notifications,
    unreadCount,
    markAllRead,
    markNotificationRead,
    clearNotifications,
  }), [
    addToast,
    clearNotifications,
    markAllRead,
    markNotificationRead,
    notifications,
    unreadCount,
  ]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-container">
        {toasts.map((notification) => (
          <ToastItem key={notification.id} toast={notification} onRemove={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}

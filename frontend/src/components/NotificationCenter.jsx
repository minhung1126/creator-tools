import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bell, CheckCircle2, Info, X, XCircle } from 'lucide-react';
import { useActivityCenter } from '../hooks/useActivityCenter';

const icons = { error: XCircle, warning: AlertTriangle, success: CheckCircle2, info: Info };

function relativeTime(value) {
  if (!value) return '';
  const delta = Date.now() - new Date(value).getTime();
  if (delta < 60_000) return '剛剛';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分鐘前`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小時前`;
  return new Date(value).toLocaleString();
}

export default function NotificationCenter({ open, onClose, onOpenTarget }) {
  const { notifications, unreadCount, loading, error, refresh, markNotificationRead, markAllNotificationsRead } = useActivityCenter();
  const [tab, setTab] = useState('all');
  const closeButtonRef = useRef(null);
  const filtered = tab === 'unread' ? notifications.filter((item) => !item.read_at) : notifications;

  useEffect(() => {
    if (!open) return undefined;
    closeButtonRef.current?.focus();
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose?.(); };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  const openNotification = async (notification) => {
    if (!notification.read_at) await markNotificationRead(notification.id);
    if (notification.task_id || notification.batch_id) onOpenTarget?.(notification.task_id, notification.batch_id);
  };

  return (
    <div className="notification-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <aside className="notification-drawer" role="dialog" aria-modal="true" aria-labelledby="notification-center-title">
        <div className="notification-drawer-header"><div><h2 id="notification-center-title"><Bell size={19} />通知中心</h2><span>{unreadCount ? `未讀 ${unreadCount} 則` : '目前沒有未讀通知'}</span></div><button ref={closeButtonRef} type="button" className="icon-button" aria-label="關閉通知中心" onClick={onClose}><X size={19} /></button></div>
        <div className="notification-tabs" role="tablist"><button type="button" role="tab" aria-selected={tab === 'all'} className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>全部</button><button type="button" role="tab" aria-selected={tab === 'unread'} className={tab === 'unread' ? 'active' : ''} onClick={() => setTab('unread')}>未讀 <span className="notification-tab-count">{unreadCount > 99 ? '99+' : unreadCount}</span></button><button type="button" className="notification-read-all" disabled={!unreadCount} onClick={() => markAllNotificationsRead()}>全部標記已讀</button></div>
        {error && <div className="notification-error"><span>{error}</span><button type="button" className="btn btn-secondary" onClick={() => refresh()}>重試</button></div>}
        <div className="notification-list" aria-live="polite">
          {loading && !notifications.length ? <div className="notification-empty">載入通知中…</div> : !filtered.length ? <div className="notification-empty"><Bell size={25} /><strong>{tab === 'unread' ? '沒有未讀通知' : '目前沒有通知'}</strong><span>任務失敗、警告與批次摘要會保存在這裡。</span></div> : filtered.map((notification) => {
            const Icon = icons[notification.severity] || Info;
            return <button type="button" className={`notification-item ${notification.read_at ? 'read' : 'unread'}`} key={notification.id} onClick={() => openNotification(notification)}><span className={`notification-icon severity-${notification.severity}`}><Icon size={17} /></span><span className="notification-copy"><strong>{notification.title}</strong><span>{notification.message}</span><small>{relativeTime(notification.created_at)}{notification.task_id ? ' · 開啟影片任務' : notification.batch_id ? ' · 開啟批次' : ''}</small></span>{!notification.read_at && <span className="notification-unread-mark" aria-label="未讀" />}</button>;
          })}
        </div>
      </aside>
    </div>
  );
}

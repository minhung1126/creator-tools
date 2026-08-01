import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clapperboard,
  Copy,
  FileSpreadsheet,
  Info,
  LayoutDashboard,
  Send,
  Settings,
  Smartphone,
  Trash2,
  Video,
  XCircle,
  Youtube,
} from 'lucide-react';
import { useToast } from './Toast';

const youtubeItems = [
  { id: 'youtube_video_drafts', label: 'Video 草稿', icon: Clapperboard },
  { id: 'youtube_shorts_drafts', label: 'Shorts 草稿', icon: Smartphone },
  { id: 'publish_clean', label: '發布草稿並清理清單', icon: Send },
];

const sheetItems = [
  { id: 'sheet_copy', label: '內容複製', icon: Copy },
];

const NOTIFICATION_ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

function formatNotificationTime(createdAt) {
  try {
    return new Intl.DateTimeFormat('zh-TW', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(createdAt));
  } catch {
    return '';
  }
}

export default function Navbar({ activeTab, setActiveTab, authUser, onLogout }) {
  const isYoutubeTab = youtubeItems.some((item) => item.id === activeTab);
  const isSheetTab = sheetItems.some((item) => item.id === activeTab);
  const [isYoutubeOpen, setIsYoutubeOpen] = useState(isYoutubeTab);
  const [isSheetOpen, setIsSheetOpen] = useState(isSheetTab);
  const [isNotificationOpen, setIsNotificationOpen] = useState(false);
  const notificationRef = useRef(null);
  const {
    notifications,
    unreadCount,
    markAllRead,
    markNotificationRead,
    clearNotifications,
  } = useToast();

  useEffect(() => {
    if (isYoutubeTab) setIsYoutubeOpen(true);
    if (isSheetTab) setIsSheetOpen(true);
  }, [isYoutubeTab, isSheetTab]);

  useEffect(() => {
    if (!isNotificationOpen) return undefined;
    const handlePointerDown = (event) => {
      if (!notificationRef.current?.contains(event.target)) setIsNotificationOpen(false);
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setIsNotificationOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isNotificationOpen]);

  const renderNavItem = (item, isChild = false) => {
    const Icon = item.icon;
    return (
      <div
        key={item.id}
        className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
        onClick={() => setActiveTab(item.id)}
        style={isChild ? { marginLeft: '22px', padding: '10px 14px', fontSize: '0.9rem' } : undefined}
      >
        <Icon size={isChild ? 16 : 18} />
        <span>{item.label}</span>
      </div>
    );
  };

  const renderGroup = ({ label, icon: Icon, items, open, setOpen, active, id }) => (
    <div>
      <button
        type="button"
        className={`nav-item ${active ? 'active' : ''}`}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={id}
        style={{ width: '100%', border: 'none', font: 'inherit', textAlign: 'left' }}
      >
        <Icon size={18} />
        <span style={{ flex: 1 }}>{label}</span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open && (
        <div id={id} style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px', marginLeft: '8px', paddingLeft: '8px', borderLeft: '1px solid var(--border-color)' }}>
          {items.map((item) => renderNavItem(item, true))}
        </div>
      )}
    </div>
  );

  return (
    <aside className="sidebar">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
          <div style={{ background: 'linear-gradient(135deg, #6366f1 0%, #ec4899 100%)', padding: '8px', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Video size={24} color="#ffffff" />
          </div>
          <div>
            <h2 style={{ fontSize: '1.15rem', color: '#fff' }}>Creator Tools</h2>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>創作者自動化控制台</p>
          </div>
        </div>
      </div>

      <nav style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {renderNavItem({ id: 'dashboard', label: '儀表板總覽', icon: LayoutDashboard })}
        {renderGroup({ label: 'YouTube', icon: Youtube, items: youtubeItems, open: isYoutubeOpen, setOpen: setIsYoutubeOpen, active: isYoutubeTab, id: 'youtube-nav-items' })}
        {renderGroup({ label: 'Sheet', icon: FileSpreadsheet, items: sheetItems, open: isSheetOpen, setOpen: setIsSheetOpen, active: isSheetTab, id: 'sheet-nav-items' })}
        {renderNavItem({ id: 'settings', label: '系統與帳號設定', icon: Settings })}
      </nav>

      <div className="sidebar-footer">
        <div className="notification-center" ref={notificationRef}>
          {isNotificationOpen && (
            <section className="notification-panel" aria-label="系統通知">
              <header className="notification-panel-header">
                <div>
                  <h3>系統通知</h3>
                  <p>{unreadCount > 0 ? `${unreadCount} 則未讀` : '目前沒有未讀通知'}</p>
                </div>
                <div className="notification-panel-actions">
                  <button type="button" onClick={markAllRead} disabled={unreadCount === 0} title="全部標為已讀" aria-label="全部標為已讀"><CheckCheck size={16} /></button>
                  <button type="button" onClick={clearNotifications} disabled={notifications.length === 0} title="清除全部通知" aria-label="清除全部通知"><Trash2 size={16} /></button>
                </div>
              </header>

              <div className="notification-list">
                {notifications.length === 0 ? (
                  <div className="notification-empty"><Bell size={22} /><span>系統通知會顯示在這裡</span></div>
                ) : notifications.map((notification) => {
                  const Icon = NOTIFICATION_ICONS[notification.type] || Info;
                  return (
                    <button
                      type="button"
                      key={notification.id}
                      className={`notification-item notification-${notification.type} ${notification.read ? 'is-read' : 'is-unread'}`}
                      onClick={() => markNotificationRead(notification.id)}
                    >
                      <Icon size={17} />
                      <span className="notification-item-content">
                        <span className="notification-message">{notification.message}</span>
                        <span className="notification-time">{formatNotificationTime(notification.createdAt)}</span>
                      </span>
                      {!notification.read && <span className="notification-unread-dot" aria-label="未讀" />}
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          <button
            type="button"
            className={`notification-button ${isNotificationOpen ? 'active' : ''}`}
            onClick={() => setIsNotificationOpen((open) => !open)}
            aria-expanded={isNotificationOpen}
            aria-label={`系統通知${unreadCount > 0 ? `，${unreadCount} 則未讀` : ''}`}
          >
            <Bell size={18} />
            <span>系統通知</span>
            {unreadCount > 0 && <span className="notification-count">{unreadCount > 99 ? '99+' : unreadCount}</span>}
          </button>
        </div>

        <div className="glass-panel" style={{ padding: '14px', fontSize: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>Google 連線狀態</span>
            {authUser ? <span className="badge badge-connected"><CheckCircle2 size={12} /> 已連線</span> : <span className="badge badge-disconnected"><XCircle size={12} /> 未連線</span>}
          </div>
          {authUser ? (
            <div>
              <p style={{ fontSize: '0.8rem', color: '#fff', wordBreak: 'break-all', fontWeight: 500 }}>{authUser.email || 'Google User'}</p>
              <button onClick={onLogout} style={{ marginTop: '8px', fontSize: '0.75rem', color: '#f87171', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>登出 / 切換帳號</button>
            </div>
          ) : <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>請至「系統設定」開啟認證連線</p>}
        </div>
      </div>
    </aside>
  );
}

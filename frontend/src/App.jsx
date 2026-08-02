import React, { useState, useEffect } from 'react';
import { ToastProvider, useToast } from './components/Toast';
import Navbar from './components/Navbar';
import DashboardPage from './pages/DashboardPage';
import BatchUpdatePage from './pages/BatchUpdatePage';
import PublishCleanerPage from './pages/PublishCleanerPage';
import SheetCopyPage from './pages/SheetCopyPage';
import SettingsPage from './pages/SettingsPage';
import YouTubeSettingsPage from './pages/YouTubeSettingsPage';
import ApiHealthPage from './pages/ApiHealthPage';
import InstagramReelsPage from './pages/InstagramReelsPage';
import InstagramHistoryPage from './pages/InstagramHistoryPage';
import InstagramSettingsPage from './pages/InstagramSettingsPage';
import LoginPage from './pages/LoginPage';
import TaskQueuePage from './pages/TaskQueuePage';
import NotificationCenter from './components/NotificationCenter';
import { ActivityCenterProvider } from './contexts/ActivityCenterContext';
import { api } from './services/api';
import { clearAuthHash, parseAuthHash } from './utils/authHash';

function AppContent() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [authUser, setAuthUser] = useState(null);
  const [sysSettings, setSysSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [instagramStatusVersion, setInstagramStatusVersion] = useState(0);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const toast = useToast();

  const fetchUser = async () => {
    try {
      const res = await api.getUserStatus();
      if (res.authenticated) {
        const user = {
          ...res.user,
          token_expires_at: res.token_expires_at,
          token_status: res.token_status,
          last_refreshed_at: res.last_refreshed_at,
          last_refresh_error: res.last_refresh_error,
        };
        setAuthUser(user); return user;
      }
      setAuthUser(null); return null;
    } catch (err) { console.error('Failed to fetch user status:', err); setAuthUser(null); return null; }
  };

  const fetchSettings = async () => {
    try {
      const [system, shared, youtube] = await Promise.all([
        api.getSystemInfo(),
        api.getSharedSettings(),
        api.getYoutubeSettings(),
      ]);
      setSysSettings({ ...(system || {}), ...(shared || {}), ...(youtube || {}) });
    }
    catch (err) { console.error('Failed to fetch system settings:', err); }
  };

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      const user = await fetchUser();
      const authResult = parseAuthHash();
      if (authResult?.type === 'google_success') {
        toast.success('Google 帳號連線成功！');
        clearAuthHash();
        const updatedUser = await fetchUser(); if (updatedUser) await fetchSettings();
      } else if (authResult?.type === 'google_error') {
        const message = authResult.value || 'Google 帳號連線失敗，請重新嘗試。';
        setAuthError(message); toast.error(message); clearAuthHash();
      } else if (authResult?.type === 'instagram_success') {
        setActiveTab('instagram_settings');
        toast.success('Instagram 帳號連線成功。');
        clearAuthHash();
        setInstagramStatusVersion((version) => version + 1);
        if (user) {
          await api.getInstagramAuthStatus().catch(() => null);
          await fetchSettings();
        }
      } else if (authResult?.type === 'instagram_error') {
        setActiveTab('instagram_settings');
        toast.error(authResult.value || 'Instagram 帳號連線失敗，請重新嘗試。');
        clearAuthHash();
        setInstagramStatusVersion((version) => version + 1);
      } else if (user) await fetchSettings();
      setLoading(false);
    };
    init();
  }, [toast]);

  useEffect(() => {
    const handleSessionExpired = () => {
      const message = '登入已逾時，請重新登入；完成後可回到任務隊列繼續查看工作。';
      setAuthUser(null);
      setAuthError(message);
      toast.warning(message, 8000);
    };
    window.addEventListener('creator-tools:session-expired', handleSessionExpired);
    return () => window.removeEventListener('creator-tools:session-expired', handleSessionExpired);
  }, [toast]);

  const handleLogout = async () => {
    try { await api.logout(); setAuthUser(null); toast.success('已成功登出 Google 帳號！'); }
    catch (err) { console.error('Logout error:', err); toast.error('登出失敗，請稍後再試'); }
  };

  if (loading) return <div className="loading-center">系統初始化中...</div>;
  if (!authUser) return <LoginPage initialError={authError} />;

  const openNotificationTarget = (taskId) => {
    if (taskId) setSelectedTaskId(taskId);
    setActiveTab('task_queue');
    setNotificationOpen(false);
  };

  return <div className="app-container"><Navbar activeTab={activeTab} setActiveTab={setActiveTab} authUser={authUser} onLogout={handleLogout} onOpenNotifications={() => setNotificationOpen(true)} /><main className="main-content">
    {activeTab === 'dashboard' && <DashboardPage authUser={authUser} sysSettings={sysSettings} setActiveTab={setActiveTab} />}
    {activeTab === 'api_health' && <ApiHealthPage />}
    {activeTab === 'youtube_video_drafts' && <BatchUpdatePage key="video-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Video" setActiveTab={setActiveTab} />}
    {activeTab === 'youtube_shorts_drafts' && <BatchUpdatePage key="shorts-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Shorts" setActiveTab={setActiveTab} />}
    {activeTab === 'publish_clean' && <PublishCleanerPage sysSettings={sysSettings} authUser={authUser} setActiveTab={setActiveTab} />}
    {activeTab === 'youtube_settings' && <YouTubeSettingsPage sysSettings={sysSettings} refreshSettings={fetchSettings} setActiveTab={setActiveTab} />}
    {activeTab === 'sheet_copy' && <SheetCopyPage sysSettings={sysSettings} />}
    {activeTab === 'instagram_reels' && <InstagramReelsPage setActiveTab={setActiveTab} />}
    {activeTab === 'instagram_history' && <InstagramHistoryPage />}
    {activeTab === 'instagram_settings' && <InstagramSettingsPage refreshKey={instagramStatusVersion} />}
    {activeTab === 'task_queue' && <TaskQueuePage selectedTaskId={selectedTaskId} />}
    {activeTab === 'settings' && <SettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} />}
  </main><NotificationCenter open={notificationOpen} onClose={() => setNotificationOpen(false)} onOpenTarget={openNotificationTarget} /></div>;
}

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, errorInfo) { console.error('ErrorBoundary caught:', error, errorInfo); }
  render() {
    if (this.state.hasError) return <div className="loading-center" style={{ flexDirection: 'column', gap: '16px' }}><h2 style={{ color: '#f87171' }}>⚠️ 應用程式發生錯誤</h2><p style={{ color: 'var(--text-muted)', maxWidth: '500px', textAlign: 'center' }}>{this.state.error?.message || '發生未預期的錯誤。'}</p><button className="btn btn-primary" onClick={() => window.location.reload()}>重新載入頁面</button></div>;
    return this.props.children;
  }
}

export default function App() { return <ErrorBoundary><ToastProvider><ActivityCenterProvider><AppContent /></ActivityCenterProvider></ToastProvider></ErrorBoundary>; }

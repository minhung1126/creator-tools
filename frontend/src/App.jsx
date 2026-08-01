import React, { useState, useEffect } from 'react';
import { ToastProvider, useToast } from './components/Toast';
import Navbar from './components/Navbar';
import DashboardPage from './pages/DashboardPage';
import BatchUpdatePage from './pages/BatchUpdatePage';
import PublishCleanerPage from './pages/PublishCleanerPage';
import SheetCopyPage from './pages/SheetCopyPage';
import SettingsPage from './pages/SettingsPage';
import InstagramReelsPage from './pages/InstagramReelsPage';
import InstagramSettingsPage from './pages/InstagramSettingsPage';
import LoginPage from './pages/LoginPage';
import { api } from './services/api';

function AppContent() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [authUser, setAuthUser] = useState(null);
  const [sysSettings, setSysSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const toast = useToast();

  const fetchUser = async () => {
    try {
      const res = await api.getUserStatus();
      if (res.authenticated) { setAuthUser(res.user); return res.user; }
      setAuthUser(null); return null;
    } catch (err) { console.error('Failed to fetch user status:', err); setAuthUser(null); return null; }
  };

  const fetchSettings = async () => {
    try { setSysSettings((await api.getSettings()) || {}); }
    catch (err) { console.error('Failed to fetch system settings:', err); }
  };

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      const user = await fetchUser();
      const hash = window.location.hash;
      if (hash.includes('auth_success=1')) {
        toast.success('Google 帳號連線成功！'); window.location.hash = '';
        const updatedUser = await fetchUser(); if (updatedUser) await fetchSettings();
      } else if (hash.includes('auth_error=')) {
        const errorText = decodeURIComponent(hash.split('auth_error=')[1] || '');
        setAuthError(`Google 帳號連線失敗：${errorText}`); toast.error(`Google 帳號連線失敗：${errorText}`); window.location.hash = '';
      } else if (hash.includes('instagram_auth_success=1')) {
        setActiveTab('instagram_settings'); toast.success('Instagram 帳號連線成功，帳號 ID 與 Token 已安全儲存。'); window.location.hash = ''; if (user) await fetchSettings();
      } else if (hash.includes('instagram_auth_error=')) {
        const errorText = decodeURIComponent(hash.split('instagram_auth_error=')[1] || '');
        setActiveTab('instagram_settings'); toast.error(`Instagram 帳號連線失敗：${errorText}`); window.location.hash = ''; if (user) await fetchSettings();
      } else if (user) await fetchSettings();
      setLoading(false);
    };
    init();
  }, []);

  const handleLogout = async () => {
    try { await api.logout(); setAuthUser(null); toast.success('已成功登出 Google 帳號！'); }
    catch (err) { console.error('Logout error:', err); toast.error('登出失敗，請稍後再試'); }
  };

  if (loading) return <div className="loading-center">系統初始化中...</div>;
  if (!authUser) return <LoginPage initialError={authError} />;

  return <div className="app-container"><Navbar activeTab={activeTab} setActiveTab={setActiveTab} authUser={authUser} onLogout={handleLogout} /><main className="main-content">
    {activeTab === 'dashboard' && <DashboardPage authUser={authUser} sysSettings={sysSettings} setActiveTab={setActiveTab} />}
    {activeTab === 'youtube_video_drafts' && <BatchUpdatePage key="video-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Video" />}
    {activeTab === 'youtube_shorts_drafts' && <BatchUpdatePage key="shorts-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Shorts" />}
    {activeTab === 'publish_clean' && <PublishCleanerPage sysSettings={sysSettings} authUser={authUser} />}
    {activeTab === 'sheet_copy' && <SheetCopyPage sysSettings={sysSettings} />}
    {activeTab === 'instagram_reels' && <InstagramReelsPage />}
    {activeTab === 'instagram_settings' && <InstagramSettingsPage />}
    {activeTab === 'settings' && <SettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} refreshUser={fetchUser} />}
  </main></div>;
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

export default function App() { return <ErrorBoundary><ToastProvider><AppContent /></ToastProvider></ErrorBoundary>; }

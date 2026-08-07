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
import LoginPage from './pages/LoginPage';
import { api } from './services/api';
import { clearAuthHash, parseAuthHash } from './utils/authHash';
import { readPersistentJson, writePersistentJson } from './utils/persistentStorage';

const NAVIGATION_STORAGE_KEY = 'creator-tools.navigation.v1';

function AppContent() {
  const [activeTab, setActiveTab] = useState(() => readPersistentJson(NAVIGATION_STORAGE_KEY, {}).activeTab || 'dashboard');
  const [authUser, setAuthUser] = useState(null);
  const [sysSettings, setSysSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const toast = useToast();

  useEffect(() => {
    writePersistentJson(NAVIGATION_STORAGE_KEY, { ...readPersistentJson(NAVIGATION_STORAGE_KEY, {}), activeTab });
  }, [activeTab]);

  const fetchUser = async () => {
    try {
      const res = await api.getUserStatus();
      if (res.authenticated) {
        const youtube = res.youtube || {
          authenticated: Boolean(res.youtube_authenticated),
          user: res.youtube_user || null,
        };
        const user = {
          ...res.user,
          token_expires_at: res.token_expires_at,
          token_status: res.token_status,
          last_refreshed_at: res.last_refreshed_at,
          last_refresh_error: res.last_refresh_error,
          youtube,
          youtube_authenticated: Boolean(res.youtube_authenticated || youtube.authenticated),
        };
        setAuthUser(user); return user;
      }
      setAuthUser(null); return null;
    } catch (err) { console.error('Failed to fetch user status:', err); setAuthUser(null); return null; }
  };

  const fetchSettings = async () => {
    try {
      const [system, shared, youtube, teamPersonFilter] = await Promise.all([
        api.getSystemInfo(),
        api.getSharedSettings(),
        api.getYoutubeSettings(),
        api.getTeamPersonFilter().catch((err) => {
          console.error('Failed to fetch shared team/person filter:', err);
          return { configured: false, team: '', selected_people: [] };
        }),
      ]);
      setSysSettings({ ...(system || {}), ...(shared || {}), ...(youtube || {}), shared_team_person_filter: teamPersonFilter });
    }
    catch (err) { console.error('Failed to fetch system settings:', err); }
  };

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      const user = await fetchUser();
      const authResult = parseAuthHash();
      if (authResult?.type === 'google_success') {
        toast.success('控制台 Google 登入成功！');
        clearAuthHash();
        const updatedUser = await fetchUser(); if (updatedUser) await fetchSettings();
      } else if (authResult?.type === 'youtube_success') {
        toast.success('YouTube 頻道 Google 授權成功！');
        clearAuthHash();
        await fetchUser();
      } else if (authResult?.type === 'google_error') {
        const message = authResult.value || '控制台 Google 登入失敗，請重新嘗試。';
        setAuthError(message); toast.error(message); clearAuthHash();
      } else if (authResult?.type === 'youtube_error') {
        const message = authResult.value || 'YouTube 頻道 Google 授權失敗，請重新嘗試。';
        toast.error(message); clearAuthHash();
      } else if (user) await fetchSettings();
      setLoading(false);
    };
    init();
  }, [toast]);

  useEffect(() => {
    const handleSessionExpired = () => {
      const message = '登入已逾時，請重新登入後再繼續操作。';
      setAuthUser(null);
      setAuthError(message);
      toast.warning(message, 8000);
    };
    window.addEventListener('creator-tools:session-expired', handleSessionExpired);
    return () => window.removeEventListener('creator-tools:session-expired', handleSessionExpired);
  }, [toast]);

  const handleLogout = async () => {
    try { await api.logout(); setAuthUser(null); toast.success('已成功登出控制台！'); }
    catch (err) { console.error('Logout error:', err); toast.error('登出失敗，請稍後再試'); }
  };

  if (loading) return <div className="loading-center">系統初始化中...</div>;
  if (!authUser) return <LoginPage initialError={authError} />;

  return <div className="app-container"><Navbar activeTab={activeTab} setActiveTab={setActiveTab} authUser={authUser} onLogout={handleLogout} /><main className="main-content">
    {activeTab === 'dashboard' && <DashboardPage authUser={authUser} sysSettings={sysSettings} setActiveTab={setActiveTab} />}
    {activeTab === 'api_health' && <ApiHealthPage />}
    {activeTab === 'youtube_video_drafts' && <BatchUpdatePage key="video-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Video" />}
    {activeTab === 'youtube_shorts_drafts' && <BatchUpdatePage key="shorts-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Shorts" />}
    {activeTab === 'publish_clean' && <PublishCleanerPage sysSettings={sysSettings} authUser={authUser} />}
    {activeTab === 'youtube_settings' && <YouTubeSettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} setActiveTab={setActiveTab} />}
    {activeTab === 'sheet_copy' && <SheetCopyPage sysSettings={sysSettings} />}
    {activeTab === 'settings' && <SettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} />}
  </main></div>;
}

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, errorInfo) { console.error('ErrorBoundary caught:', error, errorInfo); }
  render() {
    if (this.state.hasError) return <div className="loading-center error-state"><h2>⚠️ 應用程式發生錯誤</h2><p>{this.state.error?.message || '發生未預期的錯誤。'}</p><button className="btn btn-primary" onClick={() => window.location.reload()}>重新載入頁面</button></div>;
    return this.props.children;
  }
}

export default function App() { return <ErrorBoundary><ToastProvider><AppContent /></ToastProvider></ErrorBoundary>; }

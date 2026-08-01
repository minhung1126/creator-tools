import React, { useEffect, useState } from 'react';
import { ToastProvider, useToast } from './components/Toast';
import Navbar from './components/Navbar';
import DashboardPage from './pages/DashboardPage';
import BatchUpdatePage from './pages/BatchUpdatePage';
import PublishCleanerPage from './pages/PublishCleanerPage';
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
  const fetchUser = async () => { try { const res = await api.getUserStatus(); setAuthUser(res.authenticated ? res.user : null); return res.authenticated ? res.user : null; } catch { setAuthUser(null); return null; } };
  const fetchSettings = async () => { try { setSysSettings(await api.getSettings()); } catch {} };
  useEffect(() => { (async () => { const user = await fetchUser(); const hash = window.location.hash; if (hash.includes('auth_success=1')) { toast.success('Google 帳號連線成功！'); window.location.hash = ''; await fetchUser(); await fetchSettings(); } else if (hash.includes('auth_error=')) { const text = decodeURIComponent(hash.split('auth_error=')[1] || ''); setAuthError(`Google 帳號連線失敗：${text}`); window.location.hash = ''; } else if (user) await fetchSettings(); setLoading(false); })(); }, []);
  const logout = async () => { await api.logout(); setAuthUser(null); };
  if (loading) return <div className="loading-center">系統初始化中...</div>;
  if (!authUser) return <LoginPage initialError={authError} />;
  return <div className="app-container"><Navbar activeTab={activeTab} setActiveTab={setActiveTab} authUser={authUser} onLogout={logout} /><main className="main-content">
    {activeTab === 'dashboard' && <DashboardPage authUser={authUser} sysSettings={sysSettings} setActiveTab={setActiveTab} />}
    {activeTab === 'youtube_video_drafts' && <BatchUpdatePage key="video" sysSettings={sysSettings} authUser={authUser} videoType="Video" />}
    {activeTab === 'youtube_shorts_drafts' && <BatchUpdatePage key="shorts" sysSettings={sysSettings} authUser={authUser} videoType="Shorts" />}
    {activeTab === 'publish_clean' && <PublishCleanerPage sysSettings={sysSettings} authUser={authUser} />}
    {activeTab === 'instagram_reels' && <InstagramReelsPage />}
    {activeTab === 'settings' && <SettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} refreshUser={fetchUser} />}
    {activeTab === 'instagram_settings' && <InstagramSettingsPage />}
  </main></div>;
}

class ErrorBoundary extends React.Component { constructor(props) { super(props); this.state = { error: null }; } static getDerivedStateFromError(error) { return { error }; } render() { return this.state.error ? <div className="loading-center"><h2>應用程式發生錯誤</h2><button className="btn btn-primary" onClick={() => location.reload()}>重新載入</button></div> : this.props.children; } }
export default function App() { return <ErrorBoundary><ToastProvider><AppContent /></ToastProvider></ErrorBoundary>; }

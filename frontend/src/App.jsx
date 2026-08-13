import React, { useCallback, useEffect, useState } from 'react';
import { ToastProvider, useToast } from './components/Toast';
import { StatusMessage } from './components/StatusMessage';
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
import { AccountWorkStateProvider } from './hooks/useAccountWorkState';

const VALID_TABS = new Set([
  'dashboard',
  'api_health',
  'youtube_video_drafts',
  'youtube_shorts_drafts',
  'publish_clean',
  'youtube_settings',
  'sheet_copy',
  'settings',
]);

const SETTING_LABELS = ['系統設定', '共用設定', 'YouTube 設定', '團體與人物篩選', '工作狀態'];

function normalizeActiveTab(value) {
  return VALID_TABS.has(value) ? value : 'dashboard';
}

function publicRequestError(error, fallback = '操作失敗，請重試。') {
  if (error?.code === 'network_error' || error?.code === 'timeout' || !error?.status) {
    return '目前無法連線到 Creator Tools，請確認服務與網路後重試。';
  }
  if (error?.status === 401 || error?.code === 'session_expired') {
    return '登入已逾時，請重新登入後再試。';
  }
  return error?.message || fallback;
}

function AppContent() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [authUser, setAuthUser] = useState(null);
  const [sysSettings, setSysSettings] = useState({});
  const [workState, setWorkState] = useState({});
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [settingsStatus, setSettingsStatus] = useState(null);
  const [settingsRefreshing, setSettingsRefreshing] = useState(false);
  const toast = useToast();

  const fetchUser = useCallback(async () => {
    try {
      const res = await api.getUserStatus();
      if (res.authenticated) {
        const user = {
          ...res.user,
          token_expires_at: res.token_expires_at,
          token_status: res.token_status,
          last_refreshed_at: res.last_refreshed_at,
          last_refresh_error: res.last_refresh_error,
          youtube: res.youtube,
        };
        setAuthError(null);
        setAuthUser(user);
        return user;
      }
      setAuthError(null);
      setAuthUser(null);
      return null;
    } catch (error) {
      const message = publicRequestError(error, '無法確認登入狀態。');
      console.error('Failed to fetch user status:', error);
      setAuthError(message);
      setAuthUser(null);
      return null;
    }
  }, []);

  const fetchSettings = useCallback(async () => {
    setSettingsRefreshing(true);
    try {
      const requests = [
        api.getSystemInfo(),
        api.getSharedSettings(),
        api.getYoutubeSettings(),
        api.getTeamPersonFilter(),
        api.getWorkState(),
      ];
      const results = await Promise.allSettled(requests);
      const failures = results
        .map((result, index) => (result.status === 'rejected' ? { label: SETTING_LABELS[index], error: result.reason } : null))
        .filter(Boolean);
      const value = (result) => (result.status === 'fulfilled' ? result.value : null);
      const system = value(results[0]);
      const shared = value(results[1]);
      const youtube = value(results[2]);
      const teamPersonFilter = value(results[3]);
      const workStateResponse = value(results[4]);

      setSysSettings((current) => ({
        ...current,
        ...(system || {}),
        ...(shared || {}),
        ...(youtube || {}),
        ...(teamPersonFilter ? { shared_team_person_filter: teamPersonFilter } : {}),
      }));

      if (workStateResponse) {
        const nextWorkState = workStateResponse.state || {};
        setWorkState(nextWorkState);
        setActiveTab(normalizeActiveTab(nextWorkState.navigation?.activeTab));
        setSidebarCollapsed(nextWorkState.navigation?.sidebarCollapsed ?? false);
      }

      if (!failures.length) {
        setSettingsStatus(null);
      } else {
        const allConnectionFailures = failures.every(({ error }) => error?.code === 'network_error' || error?.code === 'timeout' || !error?.status);
        const message = allConnectionFailures
          ? '目前無法連線到設定服務，請確認服務與網路後重試。'
          : `部分設定尚未載入：${failures.map(({ label }) => label).join('、')}。`;
        setSettingsStatus({
          tone: failures.length === results.length ? 'error' : 'warning',
          message,
          details: failures.map(({ label, error }) => `${label}：${publicRequestError(error)}`),
        });
      }
      return { failures };
    } catch (error) {
      console.error('Failed to fetch system settings:', error);
      setSettingsStatus({ tone: 'error', message: publicRequestError(error, '目前無法載入設定，請重試。'), details: [] });
      return { failures: [{ label: '設定服務', error }] };
    } finally {
      setSettingsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      try {
        const user = await fetchUser();
        const authResult = parseAuthHash();
        if (authResult?.type === 'google_success') {
          toast.success('控制台 Google 登入成功');
          clearAuthHash();
          const updatedUser = await fetchUser();
          if (updatedUser) await fetchSettings();
        } else if (authResult?.type === 'youtube_success') {
          toast.success('YouTube 頻道 Google 授權成功');
          clearAuthHash();
          await fetchUser();
        } else if (authResult?.type === 'google_error') {
          const message = authResult.value || '控制台 Google 登入失敗，請重新嘗試。';
          setAuthError(message);
          toast.error(message);
          clearAuthHash();
        } else if (authResult?.type === 'youtube_error') {
          const message = authResult.value || 'YouTube 頻道 Google 授權失敗，請重新嘗試。';
          toast.error(message);
          clearAuthHash();
          if (user) await fetchSettings();
        } else if (user) {
          await fetchSettings();
        }
      } catch (error) {
        console.error('Application initialization failed:', error);
        setAuthError(publicRequestError(error, '系統初始化失敗，請重新嘗試。'));
      } finally {
        setLoading(false);
      }
    };
    init();
  }, [fetchSettings, fetchUser, toast]);

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
    try {
      await api.logout();
      setAuthUser(null);
      setWorkState({});
      setActiveTab('dashboard');
      setSidebarCollapsed(false);
      toast.success('已登出控制台');
    } catch (error) {
      console.error('Logout error:', error);
      toast.error('登出失敗，請稍後再試。');
    }
  };

  if (loading) return <div className="loading-center">系統初始化中…</div>;
  if (!authUser) return <LoginPage initialError={authError} />;

  return <AccountWorkStateProvider key={authUser.sub || authUser.email} initialState={workState}>
    <div className={`app-container${sidebarCollapsed ? ' sidebar-is-collapsed' : ''}`}>
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} authUser={authUser} onLogout={handleLogout} sidebarCollapsed={sidebarCollapsed} setSidebarCollapsed={setSidebarCollapsed} />
      <main className="main-content">
        {settingsStatus && (
          <StatusMessage
            tone={settingsStatus.tone}
            title="設定載入狀態"
            action={<button type="button" className="btn btn-secondary status-message-action" onClick={fetchSettings} disabled={settingsRefreshing}>{settingsRefreshing ? '更新中…' : '重試'}</button>}
          >
            <span>{settingsStatus.message}</span>
            {settingsStatus.details.length > 0 && <small>{settingsStatus.details.join('；')}</small>}
          </StatusMessage>
        )}
        {activeTab === 'dashboard' && <DashboardPage authUser={authUser} sysSettings={sysSettings} setActiveTab={setActiveTab} />}
        {activeTab === 'api_health' && <ApiHealthPage authUser={authUser} />}
        {activeTab === 'youtube_video_drafts' && <BatchUpdatePage key="video-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Video" />}
        {activeTab === 'youtube_shorts_drafts' && <BatchUpdatePage key="shorts-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Shorts" />}
        {activeTab === 'publish_clean' && <PublishCleanerPage sysSettings={sysSettings} authUser={authUser} />}
        {activeTab === 'youtube_settings' && <YouTubeSettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} refreshAuthUser={fetchUser} setActiveTab={setActiveTab} />}
        {activeTab === 'sheet_copy' && <SheetCopyPage sysSettings={sysSettings} />}
        {activeTab === 'settings' && <SettingsPage authUser={authUser} sysSettings={sysSettings} refreshSettings={fetchSettings} />}
      </main>
    </div>
  </AccountWorkStateProvider>;
}

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="loading-center error-state">
          <StatusMessage tone="error" title="應用程式暫時無法顯示">為保護錯誤內容，詳細資訊不會顯示。請重新載入頁面。</StatusMessage>
          <button className="btn btn-primary" type="button" onClick={() => window.location.reload()}>重新載入頁面</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return <ErrorBoundary><ToastProvider><AppContent /></ToastProvider></ErrorBoundary>;
}

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BrowserRouter, useInRouterContext } from 'react-router-dom';
import { ToastProvider, useToast } from './components/Toast';
import { StatusMessage } from './components/StatusMessage';
import { api } from './services/api';
import { clearAuthHash, parseAuthHash } from './utils/authHash';
import { usePageResume } from './hooks/usePageResume';
import AppRoutes from './routes/AppRoutes';
import { consumeOAuthReturnPath } from './utils/authReturnPath';
import { PATHS } from './routes/paths';
import { clearPageRecoveryParam, recoverPage } from './utils/pageRecovery';

const SETTING_LABELS = ['系統設定', '共用設定', 'YouTube 設定', '團體與人物篩選', '工作狀態'];
const AUTH_STATUS = {
  LOADING: 'loading',
  AUTHENTICATED: 'authenticated',
  UNAUTHENTICATED: 'unauthenticated',
  RECONNECTING: 'reconnecting',
};
const RESUME_RETRY_DELAYS_MS = [0, 1000, 3000];
const FRONTEND_COMMIT_SHA = import.meta.env.VITE_APP_COMMIT_SHA || 'development';

export function isConnectionFailure(error) {
  return error?.code === 'network_error'
    || error?.code === 'timeout'
    || !error?.status
    || error?.status >= 500;
}

export function hasVersionMismatch(frontendSha, backendSha) {
  const frontend = String(frontendSha || '').trim();
  const backend = String(backendSha || '').trim();
  return Boolean(frontend && backend && frontend !== backend);
}

function publicRequestError(error, fallback = '操作失敗，請重試。') {
  if (isConnectionFailure(error)) {
    return '目前無法連線到 Creator Tools，請確認服務與網路後重試。';
  }
  if (error?.status === 401 || error?.code === 'session_expired') {
    return '登入已逾時，請重新登入後再試。';
  }
  return error?.message || fallback;
}

function authUserFromResponse(response) {
  return {
    ...response.user,
    token_expires_at: response.token_expires_at,
    token_status: response.token_status,
    last_refreshed_at: response.last_refreshed_at,
    last_refresh_error: response.last_refresh_error,
    google_scopes: response.google_scopes,
    youtube: response.youtube,
  };
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function ReconnectingScreen({ error, onRetry, isResuming }) {
  return (
    <div className="loading-center error-state" role="status" aria-live="polite">
      <StatusMessage tone="warning" title="連線中斷，正在重新連線">
        <span>目前無法確認登入狀態，請檢查網路後重試。</span>
        {error && <small>{error}</small>}
      </StatusMessage>
      <div className="status-message-actions">
        <button className="btn btn-primary status-message-action" type="button" onClick={onRetry} disabled={isResuming}>
          {isResuming ? '重新連線中…' : '立即重試'}
        </button>
        <button className="btn btn-secondary status-message-action" type="button" onClick={() => recoverPage()}>
          重新開啟本頁
        </button>
      </div>
    </div>
  );
}

export function AppContent() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [authUser, setAuthUser] = useState(null);
  const [sysSettings, setSysSettings] = useState({});
  const [workState, setWorkState] = useState({});
  const [authStatus, setAuthStatusState] = useState(AUTH_STATUS.LOADING);
  const [initializing, setInitializing] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [settingsStatus, setSettingsStatus] = useState(null);
  const [settingsRefreshing, setSettingsRefreshing] = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [oauthReturnPath, setOauthReturnPath] = useState(null);
  const authUserRef = useRef(null);
  const authRequestRef = useRef(null);
  const initStartedRef = useRef(false);
  const toast = useToast();

  const setAuthStatus = useCallback((nextStatus) => {
    setAuthStatusState(nextStatus);
  }, []);

  const updateAuthUser = useCallback((nextUser) => {
    authUserRef.current = nextUser;
    setAuthUser(nextUser);
  }, []);

  const checkAuth = useCallback(async ({ source = 'manual' } = {}) => {
    if (authRequestRef.current) return authRequestRef.current;

    const request = (async () => {
      try {
        const response = await api.getUserStatus();
        if (response?.authenticated === true) {
          const user = authUserFromResponse(response);
          setAuthError(null);
          updateAuthUser(user);
          setAuthStatus(AUTH_STATUS.AUTHENTICATED);
          return { status: AUTH_STATUS.AUTHENTICATED, user, source };
        }

        if (response?.authenticated === false) {
          setAuthError(null);
          updateAuthUser(null);
          setAuthStatus(AUTH_STATUS.UNAUTHENTICATED);
          return { status: AUTH_STATUS.UNAUTHENTICATED, user: null, source };
        }

        throw new Error('登入狀態回應格式不正確。');
      } catch (error) {
        console.error('Failed to fetch user status:', error);
        const message = publicRequestError(error, '無法確認登入狀態。');
        if (error?.status === 401 || error?.code === 'session_expired') {
          updateAuthUser(null);
          setAuthError(message);
          setAuthStatus(AUTH_STATUS.UNAUTHENTICATED);
          return { status: AUTH_STATUS.UNAUTHENTICATED, user: null, error, source };
        }

        // A network/timeout/5xx response must not turn a valid existing
        // session into a login screen. Preserve the current user and let the
        // resume flow retry a bounded number of times.
        setAuthError(message);
        setAuthStatus(AUTH_STATUS.RECONNECTING);
        return { status: AUTH_STATUS.RECONNECTING, user: authUserRef.current, error, source };
      }
    })();

    authRequestRef.current = request;
    try {
      return await request;
    } finally {
      if (authRequestRef.current === request) authRequestRef.current = null;
    }
  }, [setAuthStatus, updateAuthUser]);

  const fetchUser = useCallback(async (options = {}) => {
    const result = await checkAuth(options);
    return result.user;
  }, [checkAuth]);

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
        setSidebarCollapsed(nextWorkState.navigation?.sidebarCollapsed ?? false);
      }

      if (!failures.length) {
        setSettingsStatus(null);
      } else {
        const allConnectionFailures = failures.every(({ error }) => isConnectionFailure(error));
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

  const checkBackendVersion = useCallback(async () => {
    try {
      const health = await api.getHealth();
      if (hasVersionMismatch(FRONTEND_COMMIT_SHA, health?.commit_sha)) setUpdateAvailable(true);
    } catch (error) {
      // Health is an optional version check. Authentication success remains
      // useful even when this best-effort request is unavailable.
      console.warn('Failed to compare frontend and backend versions:', error);
    }
  }, []);

  const handlePageResume = useCallback(async () => {
    let result = null;
    for (let attempt = 0; attempt < RESUME_RETRY_DELAYS_MS.length; attempt += 1) {
      const delay = RESUME_RETRY_DELAYS_MS[attempt];
      if (delay) await wait(delay);

      result = await checkAuth({ source: 'resume' });
      if (result.status === AUTH_STATUS.AUTHENTICATED) {
        await fetchSettings();
        await checkBackendVersion();
        return result;
      }
      if (result.status === AUTH_STATUS.UNAUTHENTICATED) return result;
    }
    return result;
  }, [checkAuth, checkBackendVersion, fetchSettings]);

  const pageResume = usePageResume(handlePageResume);

  useEffect(() => {
    if (initStartedRef.current) return;
    initStartedRef.current = true;

    const init = async () => {
      setInitializing(true);
      try {
        // Parse and remove the callback hash before the router can process an
        // index redirect. The return path is consumed only after validation.
        const authResult = parseAuthHash();
        if (authResult) clearAuthHash();
        clearPageRecoveryParam();
        const user = await fetchUser({ source: 'initial' });
        if (authResult?.type === 'google_success') {
          toast.success('控制台 Google 登入成功');
          const updatedUser = await fetchUser({ source: 'oauth-callback' });
          if (updatedUser) await fetchSettings();
          setOauthReturnPath(consumeOAuthReturnPath('google', PATHS.dashboard));
        } else if (authResult?.type === 'youtube_success') {
          toast.success('YouTube 頻道 Google 授權成功');
          await fetchUser({ source: 'youtube-oauth-callback' });
          setOauthReturnPath(consumeOAuthReturnPath('youtube', PATHS.youtubeConnections));
        } else if (authResult?.type === 'google_error') {
          const message = '控制台 Google 登入失敗，請重新嘗試。';
          consumeOAuthReturnPath('google', PATHS.dashboard);
          updateAuthUser(null);
          setAuthStatus(AUTH_STATUS.UNAUTHENTICATED);
          setAuthError(message);
          toast.error(message);
        } else if (authResult?.type === 'youtube_error') {
          const message = 'YouTube 頻道 Google 授權失敗，請重新嘗試。';
          toast.error(message);
          setOauthReturnPath(consumeOAuthReturnPath('youtube', PATHS.youtubeConnections));
          if (user) await fetchSettings();
        } else if (user) {
          await fetchSettings();
        }
      } catch (error) {
        console.error('Application initialization failed:', error);
        setAuthError(publicRequestError(error, '系統初始化失敗，請重新嘗試。'));
        setAuthStatus(AUTH_STATUS.RECONNECTING);
      } finally {
        setInitializing(false);
      }
    };
    init();
  }, [fetchSettings, fetchUser, setAuthStatus, toast, updateAuthUser]);

  useEffect(() => {
    const handleSessionExpired = () => {
      const message = '登入已逾時，請重新登入後再繼續操作。';
      updateAuthUser(null);
      setAuthStatus(AUTH_STATUS.UNAUTHENTICATED);
      setAuthError(message);
      toast.warning(message, 8000);
    };
    window.addEventListener('creator-tools:session-expired', handleSessionExpired);
    return () => window.removeEventListener('creator-tools:session-expired', handleSessionExpired);
  }, [setAuthStatus, toast, updateAuthUser]);

  const handleLogout = async () => {
    try {
      await api.logout();
      updateAuthUser(null);
      setAuthStatus(AUTH_STATUS.UNAUTHENTICATED);
      setAuthError(null);
      setWorkState({});
      setSidebarCollapsed(false);
      toast.success('已登出控制台');
    } catch (error) {
      console.error('Logout error:', error);
      toast.error('登出失敗，請稍後再試。');
    }
  };

  if (authStatus === AUTH_STATUS.RECONNECTING && !authUser) {
    return <ReconnectingScreen error={authError} onRetry={pageResume.retryNow} isResuming={pageResume.isResuming} />;
  }
  if (initializing || authStatus === AUTH_STATUS.LOADING) return <div className="loading-center">系統初始化中…</div>;
  return <AppRoutes
    authStatus={authStatus}
    authUser={authUser}
    authError={authError}
    workState={workState}
    updateAvailable={updateAvailable}
    settingsStatus={settingsStatus}
    settingsRefreshing={settingsRefreshing}
    fetchSettings={fetchSettings}
    fetchUser={fetchUser}
    pageResume={pageResume}
    onLogout={handleLogout}
    sidebarCollapsed={sidebarCollapsed}
    setSidebarCollapsed={setSidebarCollapsed}
    oauthReturnPath={oauthReturnPath}
    clearOAuthReturnPath={() => setOauthReturnPath(null)}
    sysSettings={sysSettings}
  />;
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
          <StatusMessage tone="error" title="應用程式暫時無法顯示">為保護錯誤內容，詳細資訊不會顯示。請重新開啟本頁。</StatusMessage>
          <button className="btn btn-primary" type="button" onClick={() => recoverPage()}>重新開啟本頁</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const content = <ErrorBoundary><ToastProvider><AppContent /></ToastProvider></ErrorBoundary>;
  // main.jsx owns the production BrowserRouter. Keeping this fallback makes
  // direct App renders in unit tests safe without creating nested routers.
  return useInRouterContext() ? content : <BrowserRouter>{content}</BrowserRouter>;
}

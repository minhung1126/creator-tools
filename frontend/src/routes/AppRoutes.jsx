import React, { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import AppShell from '../layouts/AppShell';
import AccountSettingsLayout from '../layouts/AccountSettingsLayout';
import YouTubeSettingsLayout from '../layouts/YouTubeSettingsLayout';
import BatchUpdatePage from '../pages/BatchUpdatePage';
import DashboardPage from '../pages/DashboardPage';
import ApiHealthPage from '../pages/ApiHealthPage';
import PublishCleanerPage from '../pages/PublishCleanerPage';
import SheetCopyPage from '../pages/SheetCopyPage';
import LoginPage from '../pages/LoginPage';
import NotFoundPage from '../pages/NotFoundPage';
import YoutubeConnectionsPage from '../pages/YoutubeConnectionsPage';
import YoutubeRoutingPage from '../pages/YoutubeRoutingPage';
import YoutubeQuotaPage from '../pages/YoutubeQuotaPage';
import YoutubePlaylistSettingsPage from '../pages/YoutubePlaylistSettingsPage';
import YoutubeUploadCreatePage from '../pages/YoutubeUploadCreatePage';
import YoutubeUploadJobPage from '../pages/YoutubeUploadJobPage';
import GoogleAccountSettingsPage from '../pages/GoogleAccountSettingsPage';
import GoogleSheetSettingsPage from '../pages/GoogleSheetSettingsPage';
import SystemInfoPage from '../pages/SystemInfoPage';
import RequireAuth from './RequireAuth';
import RouteEffects from './RouteEffects';
import { getSafeReturnPath, PATHS } from './paths';

function LoginRoute({ initialError }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const returnTo = getSafeReturnPath(params.get('returnTo'));
  return <LoginPage initialError={initialError} returnTo={returnTo} />;
}

function AuthenticatedLoginRedirect() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  return <Navigate replace to={getSafeReturnPath(params.get('returnTo')) || PATHS.dashboard} />;
}

export function OAuthReturnEffect({ returnPath, clearReturnPath }) {
  const navigate = useNavigate();
  useEffect(() => {
    if (!returnPath) return;
    const safePath = getSafeReturnPath(returnPath) || PATHS.dashboard;
    clearReturnPath?.();
    navigate(safePath, { replace: true });
  }, [clearReturnPath, navigate, returnPath]);
  return null;
}

export default function AppRoutes({
  authStatus,
  authUser,
  authError,
  workState,
  updateAvailable,
  settingsStatus,
  settingsRefreshing,
  fetchSettings,
  fetchUser,
  pageResume,
  onLogout,
  sidebarCollapsed,
  setSidebarCollapsed,
  oauthReturnPath,
  clearOAuthReturnPath,
  sysSettings,
}) {
  const appShellProps = {
    authUser,
    workState,
    authStatus,
    authError,
    updateAvailable,
    settingsStatus,
    settingsRefreshing,
    fetchSettings,
    pageResume,
    onLogout,
    sidebarCollapsed,
    setSidebarCollapsed,
  };
  const pageProps = { authUser, sysSettings, refreshSettings: fetchSettings, refreshAuthUser: fetchUser };

  return (
    <>
      <RouteEffects />
      <OAuthReturnEffect returnPath={oauthReturnPath} clearReturnPath={clearOAuthReturnPath} />
      <Routes>
        <Route path={PATHS.login} element={authUser ? <AuthenticatedLoginRedirect /> : <LoginRoute initialError={authError} />} />
        <Route element={<RequireAuth authStatus={authStatus} authUser={authUser}><AppShell {...appShellProps} /></RequireAuth>}>
          <Route index element={<Navigate replace to={PATHS.dashboard} />} />
          <Route path="dashboard" element={<DashboardPage authUser={authUser} sysSettings={sysSettings} />} />
          <Route path="system/health" element={<ApiHealthPage authUser={authUser} />} />
          <Route path="system/info" element={<SystemInfoPage sysSettings={sysSettings} />} />
          <Route path="youtube/drafts/videos" element={<BatchUpdatePage key="video-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Video" />} />
          <Route path="youtube/drafts/shorts" element={<BatchUpdatePage key="shorts-drafts" sysSettings={sysSettings} authUser={authUser} videoType="Shorts" />} />
          <Route path="youtube/publish-cleanup" element={<PublishCleanerPage sysSettings={sysSettings} authUser={authUser} />} />
          <Route path="sheets/copy" element={<SheetCopyPage sysSettings={sysSettings} />} />

          <Route path="youtube/uploads" element={<Navigate replace to={PATHS.youtubeUploadNew} />} />
          <Route path="youtube/uploads/new" element={<YoutubeUploadCreatePage {...pageProps} />} />
          <Route path="youtube/uploads/:jobId" element={<YoutubeUploadJobPage {...pageProps} />} />

          <Route path="youtube/settings" element={<Navigate replace to={PATHS.youtubeConnections} />} />
          <Route path="youtube/settings/*" element={<YouTubeSettingsLayout />}>
            <Route index element={<Navigate replace to="connections" />} />
            <Route path="connections" element={<YoutubeConnectionsPage {...pageProps} />} />
            <Route path="routing" element={<YoutubeRoutingPage {...pageProps} />} />
            <Route path="quota" element={<YoutubeQuotaPage {...pageProps} />} />
            <Route path="playlist" element={<YoutubePlaylistSettingsPage {...pageProps} />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>

          <Route path="settings" element={<Navigate replace to={PATHS.googleSettings} />} />
          <Route path="settings/*" element={<AccountSettingsLayout />}>
            <Route index element={<Navigate replace to="google" />} />
            <Route path="google" element={<GoogleAccountSettingsPage {...pageProps} />} />
            <Route path="sheets" element={<GoogleSheetSettingsPage {...pageProps} />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </>
  );
}

export { PATHS };

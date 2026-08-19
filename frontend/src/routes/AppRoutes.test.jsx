import React from 'react';
import { MemoryRouter, Outlet, useLocation } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import AppRoutes from './AppRoutes';
import { PATHS } from './paths';

vi.mock('../layouts/AppShell', async () => {
  const { Outlet: RouterOutlet } = await import('react-router-dom');
  return { default: () => <RouterOutlet /> };
});
vi.mock('../layouts/YouTubeSettingsLayout', async () => {
  const { Outlet: RouterOutlet } = await import('react-router-dom');
  return { default: () => <RouterOutlet /> };
});
vi.mock('../layouts/AccountSettingsLayout', async () => {
  const { Outlet: RouterOutlet } = await import('react-router-dom');
  return { default: () => <RouterOutlet /> };
});
vi.mock('../pages/DashboardPage', () => ({ default: () => <div>dashboard route</div> }));
vi.mock('../pages/ApiHealthPage', () => ({ default: () => <div>health route</div> }));
vi.mock('../pages/SystemInfoPage', () => ({ default: () => <div>info route</div> }));
vi.mock('../pages/PublishCleanerPage', () => ({ default: () => <div>publish route</div> }));
vi.mock('../pages/SheetCopyPage', () => ({ default: () => <div>sheet route</div> }));
vi.mock('../pages/BatchUpdatePage', () => ({ default: ({ videoType }) => <div>{videoType} batch route</div> }));
vi.mock('../pages/YoutubeConnectionsPage', () => ({ default: () => <div>connections route</div> }));
vi.mock('../pages/YoutubeRoutingPage', () => ({ default: () => <div>routing route</div> }));
vi.mock('../pages/YoutubeQuotaPage', () => ({ default: () => <div>quota route</div> }));
vi.mock('../pages/YoutubePlaylistSettingsPage', () => ({ default: () => <div>playlist route</div> }));
vi.mock('../pages/YoutubeUploadCreatePage', () => ({ default: () => <div>upload create route</div> }));
vi.mock('../pages/YoutubeUploadJobPage', () => ({ default: () => <div>upload job route</div> }));
vi.mock('../pages/GoogleAccountSettingsPage', () => ({ default: () => <div>google settings route</div> }));
vi.mock('../pages/GoogleSheetSettingsPage', () => ({ default: () => <div>sheet settings route</div> }));
vi.mock('../pages/LoginPage', () => ({ default: ({ returnTo }) => <div>login route {returnTo || 'none'}</div> }));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderRoutes(initialEntry, overrides = {}) {
  return render(<MemoryRouter initialEntries={[initialEntry]}>
    <AppRoutes
      authStatus="authenticated"
      authUser={{ sub: 'user-1', email: 'creator@example.com' }}
      authError={null}
      workState={{}}
      updateAvailable={false}
      settingsStatus={null}
      settingsRefreshing={false}
      fetchSettings={vi.fn()}
      fetchUser={vi.fn()}
      pageResume={{ retryNow: vi.fn(), isResuming: false }}
      onLogout={vi.fn()}
      sidebarCollapsed={false}
      setSidebarCollapsed={vi.fn()}
      oauthReturnPath={null}
      clearOAuthReturnPath={vi.fn()}
      sysSettings={{}}
      {...overrides}
    />
    <LocationProbe />
  </MemoryRouter>);
}

describe('AppRoutes', () => {
  it.each([
    [PATHS.dashboard, 'dashboard route'],
    [PATHS.systemHealth, 'health route'],
    [PATHS.systemInfo, 'info route'],
    [PATHS.youtubeVideoDrafts, 'Video batch route'],
    [PATHS.youtubeShortsDrafts, 'Shorts batch route'],
    [PATHS.youtubePublishCleanup, 'publish route'],
    [PATHS.youtubeConnections, 'connections route'],
    [PATHS.youtubeRouting, 'routing route'],
    [PATHS.youtubeQuota, 'quota route'],
    [PATHS.youtubePlaylist, 'playlist route'],
    [PATHS.youtubeUploadNew, 'upload create route'],
    [PATHS.youtubeUploadJob('example-job-id'), 'upload job route'],
    [PATHS.sheetCopy, 'sheet route'],
    [PATHS.googleSettings, 'google settings route'],
    [PATHS.sheetSettings, 'sheet settings route'],
  ])('renders %s', (path, expected) => {
    renderRoutes(path);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it.each([
    ['/', PATHS.dashboard, 'dashboard route'],
    [PATHS.youtubeSettings, PATHS.youtubeConnections, 'connections route'],
    [PATHS.settings, PATHS.googleSettings, 'google settings route'],
    [PATHS.youtubeUploads, PATHS.youtubeUploadNew, 'upload create route'],
  ])('replaces parent path %s with %s', (from, to, expected) => {
    renderRoutes(from);
    expect(screen.getByText(expected)).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(to);
  });

  it.each([
    [PATHS.youtubeSettings, PATHS.youtubeConnections],
    [PATHS.settings, PATHS.googleSettings],
    [PATHS.youtubeUploads, PATHS.youtubeUploadNew],
  ])('preserves canonical destination for unauthenticated alias %s', (alias, canonicalPath) => {
    renderRoutes(alias, { authStatus: 'unauthenticated', authUser: null });
    expect(screen.getByText(`login route ${canonicalPath}`)).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(`/login?returnTo=${encodeURIComponent(canonicalPath)}`);
  });

  it.each(['/youtube/settings/missing', '/settings/missing'])('renders 404 for unknown settings child path %s', (path) => {
    renderRoutes(path);
    expect(screen.getByText('找不到頁面')).toBeInTheDocument();
  });

  it('renders a safe 404 for an unknown protected URL', () => {
    renderRoutes('/not-a-real-page');
    expect(screen.getByText('找不到頁面')).toBeInTheDocument();
  });

  it('preserves a safe deep path when auth is missing', () => {
    renderRoutes(PATHS.youtubeVideoDrafts, { authStatus: 'unauthenticated', authUser: null });
    expect(screen.getByText('login route /youtube/drafts/videos')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login?returnTo=%2Fyoutube%2Fdrafts%2Fvideos');
  });
});

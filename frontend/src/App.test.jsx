import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App, { ErrorBoundary, hasVersionMismatch } from './App';
import { api } from './services/api';

vi.mock('./services/api', () => ({
  api: {
    getHealth: vi.fn(),
    getUserStatus: vi.fn(),
    getSystemInfo: vi.fn(),
    getSharedSettings: vi.fn(),
    getYoutubeSettings: vi.fn(),
    getTeamPersonFilter: vi.fn(),
    getWorkState: vi.fn(),
    getAuthConfig: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock('./components/Navbar', () => ({ default: () => <nav data-testid="navbar">navbar</nav> }));
vi.mock('./pages/DashboardPage', () => ({ default: () => <div data-testid="dashboard-page">dashboard</div> }));
vi.mock('./pages/BatchUpdatePage', () => ({ default: () => <div>batch</div> }));
vi.mock('./pages/PublishCleanerPage', () => ({ default: () => <div>publish</div> }));
vi.mock('./pages/SheetCopyPage', () => ({ default: () => <div>sheet copy</div> }));
vi.mock('./pages/SettingsPage', () => ({ default: () => <div>settings</div> }));
vi.mock('./pages/YouTubeSettingsPage', () => ({ default: () => <div>youtube settings</div> }));
vi.mock('./pages/ApiHealthPage', () => ({ default: () => <div>api health</div> }));
vi.mock('./pages/LoginPage', () => ({
  default: ({ initialError }) => <div data-testid="login-page">{initialError || '登入頁'}</div>,
}));
vi.mock('./hooks/useAccountWorkState', () => ({
  AccountWorkStateProvider: ({ children }) => <>{children}</>,
}));

const userResponse = {
  authenticated: true,
  user: { sub: 'subject-a', email: 'user@example.test' },
  youtube: { slots: { primary: { authenticated: false } } },
};
const networkError = { code: 'network_error', status: 0, message: 'offline' };

function setDocumentHidden(value) {
  Object.defineProperty(document, 'hidden', { configurable: true, value });
}

async function firePersistedPageShow() {
  const event = new Event('pageshow');
  Object.defineProperty(event, 'persisted', { configurable: true, value: true });
  await act(async () => { window.dispatchEvent(event); });
}

describe('App recovery state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setDocumentHidden(false);
    api.getHealth.mockResolvedValue({ commit_sha: 'development' });
    api.getUserStatus.mockResolvedValue({ authenticated: false });
    api.getSystemInfo.mockResolvedValue({});
    api.getSharedSettings.mockResolvedValue({});
    api.getYoutubeSettings.mockResolvedValue({});
    api.getTeamPersonFilter.mockResolvedValue({});
    api.getWorkState.mockResolvedValue({ state: {} });
    api.getAuthConfig.mockResolvedValue({ has_client_id: true, has_client_secret: true });
    api.logout.mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    setDocumentHidden(false);
  });

  it('shows reconnecting on an initial network failure instead of a blank or login page', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    api.getUserStatus.mockRejectedValueOnce(networkError);

    render(<App />);

    expect(await screen.findByText('連線中斷，正在重新連線')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '立即重試' })).toBeInTheDocument();
  });

  it('keeps the authenticated screen when a resume request fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    api.getUserStatus.mockResolvedValueOnce(userResponse);
    render(<App />);
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();

    api.getUserStatus.mockRejectedValueOnce(networkError).mockImplementation(() => new Promise(() => {}));
    await firePersistedPageShow();

    expect(await screen.findByText('連線中斷，正在重新連線')).toBeInTheDocument();
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  it('switches to the login page only when the API explicitly reports unauthenticated', async () => {
    api.getUserStatus.mockResolvedValueOnce(userResponse);
    render(<App />);
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();

    api.getUserStatus.mockResolvedValueOnce({ authenticated: false });
    await firePersistedPageShow();

    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
  });

  it('rechecks authentication for a persisted pageshow event', async () => {
    api.getUserStatus.mockResolvedValue(userResponse);
    render(<App />);
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    const callsAfterInit = api.getUserStatus.mock.calls.length;

    await firePersistedPageShow();

    await waitFor(() => expect(api.getUserStatus).toHaveBeenCalledTimes(callsAfterInit + 1));
  });

  it('shows a non-destructive update prompt when the backend build changes', async () => {
    api.getUserStatus.mockResolvedValue(userResponse);
    api.getHealth.mockResolvedValue({ commit_sha: 'new-backend-sha' });
    render(<App />);
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();

    await firePersistedPageShow();

    expect(await screen.findByText('Creator Tools 已更新，請重新載入。')).toBeInTheDocument();
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
  });

  it('rechecks after being hidden longer than the threshold', async () => {
    vi.useFakeTimers();
    api.getUserStatus.mockResolvedValue(userResponse);
    render(<App />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
    const callsAfterInit = api.getUserStatus.mock.calls.length;

    setDocumentHidden(true);
    await act(async () => { fireEvent(document, new Event('visibilitychange')); });
    const hiddenStartedAt = Date.now();
    vi.setSystemTime(hiddenStartedAt + 5 * 60 * 1000 + 1);
    setDocumentHidden(false);
    await act(async () => { fireEvent(document, new Event('visibilitychange')); });
    await act(async () => { await Promise.resolve(); });
    expect(api.getUserStatus).toHaveBeenCalledTimes(callsAfterInit + 1);
  });

  it('shares one recovery request across simultaneous resume events', async () => {
    let resolveRecovery;
    api.getUserStatus.mockResolvedValueOnce(userResponse).mockImplementationOnce(() => new Promise((resolve) => {
      resolveRecovery = resolve;
    }));
    render(<App />);
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    const callsAfterInit = api.getUserStatus.mock.calls.length;

    await firePersistedPageShow();
    window.dispatchEvent(new Event('online'));

    await waitFor(() => expect(api.getUserStatus).toHaveBeenCalledTimes(callsAfterInit + 1));
    resolveRecovery(userResponse);
    await waitFor(() => expect(screen.getByTestId('dashboard-page')).toBeInTheDocument());
    expect(api.getUserStatus).toHaveBeenCalledTimes(callsAfterInit + 1);
  });

  it('uses online to recover from the initial reconnecting state', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    api.getUserStatus.mockRejectedValueOnce(networkError);
    render(<App />);
    expect(await screen.findByText('連線中斷，正在重新連線')).toBeInTheDocument();

    api.getUserStatus.mockResolvedValueOnce(userResponse);
    window.dispatchEvent(new Event('online'));

    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
  });

  it('identifies a backend/frontend build mismatch without automatically reloading', () => {
    expect(hasVersionMismatch('sha-a', 'sha-b')).toBe(true);
    expect(hasVersionMismatch('sha-a', 'sha-a')).toBe(false);
    expect(hasVersionMismatch('', 'sha-a')).toBe(false);
  });
});

describe('ErrorBoundary', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows a safe recovery message without exposing the original JavaScript error', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});

    function BrokenComponent() {
      throw new Error('private implementation details');
    }

    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('應用程式暫時無法顯示')).toBeInTheDocument();
    expect(screen.getByText('為保護錯誤內容，詳細資訊不會顯示。請重新開啟本頁。')).toBeInTheDocument();
    expect(screen.queryByText('private implementation details')).not.toBeInTheDocument();
  });
});

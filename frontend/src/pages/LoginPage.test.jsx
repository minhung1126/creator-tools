import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import LoginPage from './LoginPage';

vi.mock('../services/api', () => ({
  api: {
    getAuthConfig: vi.fn(),
    getAuthUrl: vi.fn(),
  },
}));

describe('LoginPage readiness', () => {
  beforeEach(() => vi.clearAllMocks());

  it('prevents a dead-end OAuth attempt and can recover after configuration changes', async () => {
    api.getAuthConfig
      .mockResolvedValueOnce({ has_client_id: false, has_client_secret: false })
      .mockResolvedValueOnce({ has_client_id: true, has_client_secret: true });
    render(<LoginPage />);

    const loginButton = await screen.findByRole('button', { name: '使用 Google 帳號登入' });
    await waitFor(() => expect(loginButton).toBeDisabled());
    expect(screen.getByText(/OAuth 憑證/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重新檢查' }));

    await waitFor(() => expect(loginButton).toBeEnabled());
    expect(screen.queryByText(/OAuth 憑證/)).not.toBeInTheDocument();
  });

  it('keeps an OAuth callback error visible when readiness later succeeds', async () => {
    api.getAuthConfig.mockResolvedValue({ has_client_id: true, has_client_secret: true });
    render(<LoginPage initialError="Google 登入 callback 失敗，請重新嘗試。" />);

    await waitFor(() => expect(api.getAuthConfig).toHaveBeenCalledOnce());
    expect(screen.getByText('Google 登入 callback 失敗，請重新嘗試。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '使用 Google 帳號登入' })).toBeEnabled();
  });

  it('clears only the readiness error after a successful recheck', async () => {
    api.getAuthConfig
      .mockResolvedValueOnce({ has_client_id: false, has_client_secret: false })
      .mockResolvedValueOnce({ has_client_id: true, has_client_secret: true });
    render(<LoginPage initialError="Google OAuth callback 失敗。" />);

    await screen.findByText(/OAuth 憑證/);
    expect(screen.getByText('Google OAuth callback 失敗。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新檢查' }));

    await waitFor(() => expect(screen.queryByText(/OAuth 憑證/)).not.toBeInTheDocument());
    expect(screen.getByText('Google OAuth callback 失敗。')).toBeInTheDocument();
  });

  it('describes the login and YouTube authorizations as separate scopes', async () => {
    api.getAuthConfig.mockResolvedValue({ has_client_id: true, has_client_secret: true });
    render(<LoginPage />);

    await waitFor(() => expect(screen.getByText(/YouTube 頻道授權會在登入後的 YouTube 設定頁另外管理/)).toBeInTheDocument());
    expect(screen.getByText(/唯讀方式讀取工作流程需要的 Google Sheet/)).toBeInTheDocument();
  });
});

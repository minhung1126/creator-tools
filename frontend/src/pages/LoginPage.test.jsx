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
});

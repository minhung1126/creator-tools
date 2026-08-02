import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import { ToastProvider } from '../components/Toast';
import InstagramReelsPage from './InstagramReelsPage';

vi.mock('../services/api', () => ({
  api: {
    getInstagramSettings: vi.fn(),
    getInstagramAuthStatus: vi.fn(),
  },
}));

vi.mock('../hooks/useActivityCenter', () => ({
  useActivityCenter: () => ({
    refresh: vi.fn(),
    tasks: [],
    cancelTask: vi.fn(),
    retryTask: vi.fn(),
  }),
}));

describe('InstagramReelsPage setup readiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    api.getInstagramSettings.mockResolvedValue({
      drive_folder_id: '',
      spreadsheet_id: '',
      r2_account_id: '',
      r2_access_key_id: '',
      r2_bucket_name: '',
      r2_public_base_url: '',
      r2_secret_access_key_configured: false,
    });
    api.getInstagramAuthStatus.mockResolvedValue({
      app_configured: false,
      connected: false,
      expired: false,
      account: null,
    });
  });

  it('explains missing setup and takes the user directly to settings', async () => {
    const setActiveTab = vi.fn();
    render(<ToastProvider><InstagramReelsPage setActiveTab={setActiveTab} /></ToastProvider>);

    await waitFor(() => expect(screen.getByText(/Instagram App 尚未設定/)).toBeInTheDocument());
    expect(screen.getByText(/Cloudflare R2 設定尚未完成/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '前往修正設定' }));
    expect(setActiveTab).toHaveBeenCalledWith('instagram_settings');
  });
});

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '../components/Toast';
import { api } from '../services/api';
import YouTubeSettingsPage, { normalizeSlotRecord } from './YouTubeSettingsPage';

vi.mock('../services/api', () => ({
  api: {
    updateYoutubeQuota: vi.fn(),
    updateYoutubePlaylist: vi.fn(),
    updateYoutubeRoutingMode: vi.fn(),
    getYoutubeAuthUrl: vi.fn(),
    activateYoutubeSlot: vi.fn(),
    disconnectYoutube: vi.fn(),
  },
  normalizeYoutubePlaylistInput: (value) => {
    const trimmed = String(value ?? '').trim();
    if (!trimmed) return '';
    if (/^[A-Za-z0-9_-]{1,128}$/.test(trimmed)) return trimmed;
    try {
      const parsed = new URL(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`);
      if (!/(^|\.)youtube\.com$/i.test(parsed.hostname) && parsed.hostname.toLowerCase() !== 'youtu.be') return '';
      const playlistId = parsed.searchParams.get('list')?.trim() || '';
      return /^[A-Za-z0-9_-]{1,128}$/.test(playlistId) ? playlistId : '';
    } catch {
      return '';
    }
  },
}));

const primarySlot = {
  label: 'Primary', configured: true, enabled: true, authenticated: true, can_be_active: true,
  user: { email: 'creator@example.com' }, channel_id: 'channel-1', channel_title: 'Creator Channel',
  quota_limit: 10000, safety_buffer_units: 1000,
};
const secondarySlot = {
  label: 'Secondary', configured: true, enabled: true, authenticated: false, can_be_active: false,
  quota_limit: 9000, safety_buffer_units: 900,
};

function renderPage(overrides = {}) {
  const props = {
    authUser: {
      youtube: { active_slot: 'primary', slots: { primary: primarySlot, secondary: secondarySlot } },
    },
    sysSettings: { default_playlist_id: 'saved-playlist', quota_limit: 10000, safety_buffer_units: 1000 },
    refreshSettings: vi.fn().mockResolvedValue({}),
    refreshAuthUser: vi.fn().mockResolvedValue({}),
    setActiveTab: vi.fn(),
    ...overrides,
  };
  return render(<ToastProvider><YouTubeSettingsPage {...props} /></ToastProvider>);
}

describe('YouTubeSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.updateYoutubeQuota.mockResolvedValue({});
    api.updateYoutubePlaylist.mockResolvedValue({});
    api.updateYoutubeRoutingMode.mockResolvedValue({});
    api.getYoutubeAuthUrl.mockResolvedValue({ auth_url: 'https://accounts.google.com/oauth' });
    api.activateYoutubeSlot.mockResolvedValue({});
    api.disconnectYoutube.mockResolvedValue({});
  });

  it('preserves backend channel_mismatch and an explicit can_be_active false', () => {
    expect(normalizeSlotRecord('secondary', {
      authenticated: true,
      can_be_active: false,
      channel_mismatch: true,
    })).toMatchObject({
      authenticated: true,
      can_be_active: false,
      channel_mismatch: true,
    });
  });

  it('saves quota and playlist through separate actions without crossing unsaved drafts', async () => {
    renderPage();

    fireEvent.change(screen.getByPlaceholderText('YouTube Playlist ID 或網址'), {
      target: { value: 'https://www.youtube.com/playlist?list=PL_unsaved' },
    });
    fireEvent.change(document.getElementById('primary-quota-limit'), { target: { value: '8000' } });
    fireEvent.click(screen.getAllByRole('button', { name: '儲存 slot 設定' })[0]);

    await waitFor(() => expect(api.updateYoutubeQuota).toHaveBeenCalledWith({
      slot: 'primary',
      quotaLimit: 8000,
      safetyBufferUnits: 1000,
    }));
    expect(api.updateYoutubePlaylist).not.toHaveBeenCalled();

    await waitFor(() => expect(screen.getByRole('button', { name: '儲存預設播放清單' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '儲存預設播放清單' }));
    await waitFor(() => expect(api.updateYoutubePlaylist).toHaveBeenCalledWith({
      playlistId: 'PL_unsaved',
    }));
  });

  it('confirms every disconnect and explains the active-slot impact', async () => {
    renderPage({
      authUser: {
        youtube: {
          routing_mode: 'manual',
          active_slot: 'primary',
          slots: {
            primary: primarySlot,
            secondary: { ...secondarySlot, authenticated: true, can_be_active: true },
          },
        },
      },
    });

    fireEvent.click(screen.getAllByRole('button', { name: '斷開' })[0]);
    expect(screen.getByRole('dialog')).toHaveTextContent('目前作用中的');
    expect(screen.getByRole('dialog')).toHaveTextContent('新的 YouTube request 將暫時無法執行');
    expect(api.disconnectYoutube).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '取消' }));

    fireEvent.click(screen.getAllByRole('button', { name: '斷開' })[1]);
    expect(screen.getByRole('dialog')).toHaveTextContent('目前作用中的 request context 不受影響');
    fireEvent.click(screen.getByRole('button', { name: '確認斷開' }));

    await waitFor(() => expect(api.disconnectYoutube).toHaveBeenCalledWith('secondary', { confirm: true }));
  });

  it('locks conflicting authorization controls while one OAuth operation is running', async () => {
    let rejectAuth;
    api.getYoutubeAuthUrl.mockReturnValue(new Promise((resolve, reject) => {
      rejectAuth = reject;
    }));
    renderPage({
      authUser: {
        youtube: {
          active_slot: 'primary',
          slots: { primary: primarySlot, secondary: { ...secondarySlot, authenticated: false, can_be_active: true } },
        },
      },
    });

    fireEvent.click(screen.getByRole('button', { name: '重新授權' }));
    await waitFor(() => expect(api.getYoutubeAuthUrl).toHaveBeenCalledWith('primary'));
    expect(screen.getByRole('button', { name: '連結此 slot' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '斷開' })).toBeDisabled();

    rejectAuth(new Error('測試取消'));
    await waitFor(() => expect(screen.getByRole('button', { name: '連結此 slot' })).toBeEnabled());
  });
});

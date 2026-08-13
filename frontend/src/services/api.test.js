import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, normalizeYoutubePlaylistInput, resetSessionExpiredNotification } from './api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  resetSessionExpiredNotification();
});

describe('API request recovery', () => {
  it('uses the backend detail and announces an expired session', async () => {
    const expired = vi.fn();
    window.addEventListener('creator-tools:session-expired', expired, { once: true });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: '請重新登入' }),
    }));

    await expect(api.getSystemInfo()).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      code: 'session_expired',
      message: '請重新登入',
    });
    expect(expired).toHaveBeenCalledOnce();
  });

  it('turns a network failure into a clear retry message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(api.getSystemInfo()).rejects.toEqual(expect.objectContaining({
      name: 'ApiError',
      code: 'network_error',
      message: expect.stringContaining('確認服務與網路後重試'),
    }));
  });

  it('aborts a request that would otherwise wait forever', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));

    const request = api.getSystemInfo();
    const assertion = expect(request).rejects.toEqual(expect.objectContaining({
      code: 'timeout',
      message: expect.stringContaining('連線逾時'),
    }));
    await vi.advanceTimersByTimeAsync(45_000);

    await assertion;
    expect(ApiError).toBeTypeOf('function');
  });

  it('keeps structured error detail codes from the backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({ detail: { code: 'youtube_quota_exhausted', message: '配額已用完', reset_at: 'reset' } }),
    }));
    await expect(api.getYoutubeQuotaUsage()).rejects.toMatchObject({
      status: 429,
      code: 'youtube_quota_exhausted',
      details: { reset_at: 'reset' },
      message: '配額已用完',
    });
  });

  it('sends queue-free YouTube metadata input and returns direct per-video results', async () => {
    const directResult = {
      completed: true,
      total_count: 1,
      succeeded_count: 1,
      results: [{ video_id: 'video-1', status: 'succeeded' }],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => directResult,
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.batchUpdateMetadata({
      spreadsheetUrlOrId: 'sheet-id',
      playlistId: 'https://www.youtube.com/playlist?list=PL123_abc-789',
      videoType: 'Video',
      worksheetName: 'Youtube Video',
      titleColumn: 'Youtube Title',
      descriptionColumn: 'Youtube Description',
      team: 'Team',
      assignments: [{ video_id: 'video-1', person: 'Alice' }],
      previewToken: 'signed-preview-token',
      previewSnapshot: { playlist_id: 'PL123_abc-789' },
    })).resolves.toEqual(directResult);

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({
      spreadsheet_url_or_id: 'sheet-id',
      playlist_id: 'PL123_abc-789',
      video_type: 'Video',
      worksheet_name: 'Youtube Video',
      title_column: 'Youtube Title',
      description_column: 'Youtube Description',
      team: 'Team',
      assignments: [{ video_id: 'video-1', person: 'Alice' }],
      preview_token: 'signed-preview-token',
      preview_snapshot: { playlist_id: 'PL123_abc-789' },
    });
  });

  it('handles non-JSON errors and exposes Retry-After in Traditional Chinese', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      text: async () => '<html><body>busy</body></html>',
      headers: { get: (name) => (name === 'Retry-After' ? '7' : null) },
    }));

    await expect(api.getYoutubeQuotaUsage()).rejects.toMatchObject({
      status: 429,
      code: 'request_failed',
      retryAfter: 7,
      message: '服務目前忙碌或已達 API 用量限制，請約 7 秒後再試。',
      details: null,
    });
  });

  it('announces one session-expired event for parallel 401 responses', async () => {
    const expired = vi.fn();
    window.addEventListener('creator-tools:session-expired', expired);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: { code: 'login_required', message: '請重新登入', reason: 'expired' } }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await Promise.all([
      api.getSystemInfo().catch(() => null),
      api.getSharedSettings().catch(() => null),
    ]);

    expect(expired).toHaveBeenCalledOnce();
    window.removeEventListener('creator-tools:session-expired', expired);
  });

  it('keeps the primary quota menu and hides an unavailable secondary slot', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        authenticated: true,
        youtube: {
          active_slot: 'primary',
          slots: {
            primary: { enabled: true, configured: true },
            secondary: { enabled: false, configured: false },
          },
        },
      }),
    }));

    await expect(api.getUserStatus()).resolves.toMatchObject({
      youtube: { slots: { primary: { configured: true } } },
    });
    const result = await api.getUserStatus();
    expect(result.youtube.slots.secondary).toBeUndefined();
  });

  it('sends single-video YouTube metadata updates', async () => {
    const updated = { video_id: 'video-1', title: 'New title', description: 'New description', status: 'succeeded' };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => updated,
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.updateYoutubeVideoMetadata({
      videoId: 'video-1',
      title: 'New title',
      description: 'New description',
    })).resolves.toEqual(updated);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/youtube/video-metadata');
    expect(JSON.parse(options.body)).toEqual({
      video_id: 'video-1',
      title: 'New title',
      description: 'New description',
    });
  });

  it('routes secondary OAuth and quota requests by slot', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.getYoutubeAuthUrl('secondary');
    await api.activateYoutubeSlot('secondary');
    await api.getYoutubeQuotaUsage('secondary');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/auth/youtube/secondary/url',
      '/api/v1/auth/youtube/secondary/activate',
      '/api/v1/youtube/quota-usage?slot=secondary',
    ]);
  });

  it('normalizes playlist URLs before sending the compatible resource payload', async () => {
    expect(normalizeYoutubePlaylistInput('  PL123_abc-789  ')).toBe('PL123_abc-789');
    expect(normalizeYoutubePlaylistInput('https://www.youtube.com/playlist?list=PL123_abc-789')).toBe('PL123_abc-789');
    expect(normalizeYoutubePlaylistInput(`javascript:${['alert', '(1)'].join('')}`)).toBe('');
    expect(normalizeYoutubePlaylistInput('https://example.com/playlist?list=PL123_abc-789')).toBe('');

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'success' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.updateYoutubePlaylist({
      playlistId: 'https://www.youtube.com/playlist?list=PL123_abc-789',
      quotaLimit: 10000,
      safetyBufferUnits: 1000,
    });
    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({
      default_playlist_id: 'PL123_abc-789',
    });
  });

  it('does not cross-write playlist data when saving an isolated quota policy', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'success' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.updateYoutubeQuota({
      slot: 'secondary',
      defaultPlaylistId: 'saved-playlist',
      quotaLimit: 8000,
      safetyBufferUnits: 500,
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      slot: 'secondary',
      quota_limit: 8000,
      safety_buffer_units: 500,
    });
  });
});

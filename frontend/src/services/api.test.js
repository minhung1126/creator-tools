import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
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
      videoType: 'Video',
      worksheetName: 'Youtube Video',
      titleColumn: 'Youtube Title',
      descriptionColumn: 'Youtube Description',
      team: 'Team',
      assignments: [{ video_id: 'video-1', person: 'Alice' }],
    })).resolves.toEqual(directResult);

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({
      spreadsheet_url_or_id: 'sheet-id',
      video_type: 'Video',
      worksheet_name: 'Youtube Video',
      title_column: 'Youtube Title',
      description_column: 'Youtube Description',
      team: 'Team',
      assignments: [{ video_id: 'video-1', person: 'Alice' }],
    });
  });
});

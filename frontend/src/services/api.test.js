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

    await expect(api.getActivitySummary()).rejects.toMatchObject({
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
});

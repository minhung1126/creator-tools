import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePageResume } from './usePageResume';

function setDocumentHidden(value) {
  Object.defineProperty(document, 'hidden', { configurable: true, value });
}

afterEach(() => {
  vi.useRealTimers();
  setDocumentHidden(false);
});

describe('usePageResume', () => {
  it('shares one in-flight resume request and exposes its busy state', async () => {
    let release;
    const onResume = vi.fn(() => new Promise((resolve) => { release = resolve; }));
    const { result } = renderHook(() => usePageResume(onResume, { cooldownMs: 0 }));

    let first;
    let second;
    act(() => {
      first = result.current.requestResume({ reason: 'pageshow-persisted' });
      second = result.current.requestResume({ reason: 'online' });
    });
    expect(first).toBe(second);
    expect(result.current.isResuming).toBe(true);
    await waitFor(() => expect(onResume).toHaveBeenCalledOnce());

    await act(async () => {
      release({ status: 'ok' });
      await first;
    });
    expect(onResume).toHaveBeenCalledOnce();
    expect(onResume).toHaveBeenCalledWith({ reason: 'pageshow-persisted' });
    expect(result.current.isResuming).toBe(false);
  });

  it('honors the cooldown but lets an explicit retry bypass it', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const onResume = vi.fn().mockResolvedValue({ status: 'ok' });
    const { result } = renderHook(() => usePageResume(onResume, { cooldownMs: 1000 }));

    await act(async () => {
      await result.current.requestResume({ reason: 'online' });
    });
    await act(async () => {
      await result.current.requestResume({ reason: 'pageshow-persisted' });
    });
    expect(onResume).toHaveBeenCalledOnce();

    await act(async () => {
      await result.current.retryNow();
    });
    expect(onResume).toHaveBeenCalledTimes(2);
    expect(onResume).toHaveBeenLastCalledWith({ reason: 'manual' });
  });
});

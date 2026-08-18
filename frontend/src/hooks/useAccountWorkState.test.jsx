import React from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import useAccountWorkState, { AccountWorkStateProvider } from './useAccountWorkState';

vi.mock('../services/api', () => ({
  api: {
    updateWorkState: vi.fn(),
  },
}));

function wrapper({ children }) {
  return <AccountWorkStateProvider initialState={{ navigation: { sidebarCollapsed: false } }}>{children}</AccountWorkStateProvider>;
}

describe('useAccountWorkState', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => vi.useRealTimers());

  it('debounces a save and merges the server state after it succeeds', async () => {
    vi.useFakeTimers();
    api.updateWorkState.mockResolvedValue({
      state: { navigation: { sidebarCollapsed: true, serverRevision: 3 } },
    });
    const { result } = renderHook(() => useAccountWorkState('navigation'), { wrapper });

    let savePromise;
    act(() => {
      savePromise = result.current.save({ sidebarCollapsed: true }, { debounceMs: 50 });
    });

    expect(api.updateWorkState).not.toHaveBeenCalled();
    expect(result.current.value).toEqual({ sidebarCollapsed: true });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
      await savePromise;
    });

    expect(api.updateWorkState).toHaveBeenCalledWith('navigation', { sidebarCollapsed: true });
    expect(result.current.value).toEqual({ sidebarCollapsed: true, serverRevision: 3 });
    expect(result.current.saved).toBe(true);
    expect(result.current.saving).toBe(false);
  });

  it('persists a newer value after an earlier request is already in flight', async () => {
    let releaseFirst;
    api.updateWorkState
      .mockImplementationOnce(() => new Promise((resolve) => { releaseFirst = resolve; }))
      .mockResolvedValueOnce({ state: {} });
    const { result } = renderHook(() => useAccountWorkState('navigation'), { wrapper });

    let firstSave;
    await act(async () => {
      firstSave = result.current.save({ sidebarCollapsed: false }, { debounceMs: 0 });
      await Promise.resolve();
    });
    expect(api.updateWorkState).toHaveBeenCalledTimes(1);

    let secondSave;
    act(() => {
      secondSave = result.current.save({ sidebarCollapsed: true }, { debounceMs: 0 });
    });

    await act(async () => {
      releaseFirst({ state: { fromFirstRequest: true } });
      await firstSave;
      await secondSave;
    });

    expect(api.updateWorkState).toHaveBeenNthCalledWith(1, 'navigation', { sidebarCollapsed: false });
    expect(api.updateWorkState).toHaveBeenNthCalledWith(2, 'navigation', { sidebarCollapsed: true });
    expect(result.current.value).toEqual({ sidebarCollapsed: true });
    expect(result.current.saved).toBe(true);
  });

  it('exposes a failed save and retries the latest desired value', async () => {
    api.updateWorkState
      .mockRejectedValueOnce(new Error('伺服器忙碌'))
      .mockResolvedValueOnce({ state: {} });
    const { result } = renderHook(() => useAccountWorkState('navigation'), { wrapper });

    await act(async () => {
      await result.current.save({ sidebarCollapsed: true }, { debounceMs: 0 });
    });
    expect(result.current.error).toBe('伺服器忙碌');
    expect(result.current.saved).toBe(false);

    await act(async () => {
      await result.current.retry();
    });

    expect(api.updateWorkState).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBe('');
    expect(result.current.saved).toBe(true);
  });
});

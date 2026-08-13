import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import useSharedTeamPersonFilterPersistence from './useSharedTeamPersonFilterPersistence';

vi.mock('../services/api', () => ({
  api: {
    updateTeamPersonFilter: vi.fn(),
  },
}));

describe('useSharedTeamPersonFilterPersistence', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => vi.useRealTimers());

  it('waits for readiness and saves one normalized shared filter', async () => {
    api.updateTeamPersonFilter.mockResolvedValue({ configured: true });
    const { result, rerender } = renderHook(
      (props) => useSharedTeamPersonFilterPersistence(props),
      {
        initialProps: {
          team: ' 團體 ',
          selectedPeople: [' 甲 ', '甲', ''],
          ready: false,
        },
      },
    );

    expect(api.updateTeamPersonFilter).not.toHaveBeenCalled();
    rerender({ team: ' 團體 ', selectedPeople: [' 甲 ', '甲', ''], ready: true });

    await waitFor(() => expect(api.updateTeamPersonFilter).toHaveBeenCalledTimes(1), { timeout: 2000 });
    await waitFor(() => expect(result.current.saved).toBe(true), { timeout: 2000 });

    expect(api.updateTeamPersonFilter).toHaveBeenCalledTimes(1);
    expect(api.updateTeamPersonFilter).toHaveBeenCalledWith({ team: '團體', selectedPeople: ['甲'] });
    expect(result.current.saved).toBe(true);
    expect(result.current.error).toBe('');
  });

  it('reports a failed sync and retries without changing the desired filter', async () => {
    const onError = vi.fn();
    api.updateTeamPersonFilter
      .mockRejectedValueOnce(new Error('網路中斷'))
      .mockResolvedValueOnce({ configured: true });
    const { result } = renderHook(
      (props) => useSharedTeamPersonFilterPersistence(props),
      { initialProps: { team: '團體', selectedPeople: ['甲'], ready: true, onError } },
    );

    await waitFor(() => expect(result.current.error).toBe('帳號隊伍／人物篩選同步失敗：網路中斷'), { timeout: 2000 });
    expect(result.current.error).toBe('帳號隊伍／人物篩選同步失敗：網路中斷');
    expect(onError).toHaveBeenLastCalledWith('帳號隊伍／人物篩選同步失敗：網路中斷');

    await act(async () => {
      await result.current.retry();
    });

    expect(api.updateTeamPersonFilter).toHaveBeenCalledTimes(2);
    expect(api.updateTeamPersonFilter).toHaveBeenLastCalledWith({ team: '團體', selectedPeople: ['甲'] });
    expect(result.current.saved).toBe(true);
    expect(result.current.error).toBe('');
    expect(onError).toHaveBeenLastCalledWith('');
  });
});

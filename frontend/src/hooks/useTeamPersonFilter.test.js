import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import useTeamPersonFilter from './useTeamPersonFilter';

describe('useTeamPersonFilter', () => {
  it('loads teams and defaults a newly selected team to all people in API order', async () => {
    const apiClient = {
      parseSheetOptions: vi.fn().mockResolvedValue({ teams: ['團體 B', '團體 A'] }),
      getTeamPeople: vi.fn().mockResolvedValue({ people: ['全團體', '乙', '甲'] }),
    };
    const { result } = renderHook(() => useTeamPersonFilter({ source: 'sheet', worksheetName: '工作表', apiClient }));

    await waitFor(() => expect(result.current.teams).toEqual(['團體 B', '團體 A']));
    expect(result.current.selectedTeam).toBe('');

    act(() => result.current.setSelectedTeam('團體 A'));
    await waitFor(() => expect(result.current.people).toEqual(['全團體', '乙', '甲']));
    expect(result.current.selectedPeople).toEqual(['全團體', '乙', '甲']);
    expect(apiClient.getTeamPeople).toHaveBeenCalledWith('sheet', '工作表', '團體 A');
  });

  it('ignores an older people response after a fast team switch', async () => {
    let resolveOld;
    let resolveNew;
    const apiClient = {
      parseSheetOptions: vi.fn().mockResolvedValue({ teams: ['舊團體', '新團體'] }),
      getTeamPeople: vi.fn((_, __, team) => new Promise((resolve) => {
        if (team === '舊團體') resolveOld = resolve;
        else resolveNew = resolve;
      })),
    };
    const { result } = renderHook(() => useTeamPersonFilter({ source: 'sheet', worksheetName: '工作表', apiClient }));
    await waitFor(() => expect(result.current.teams).toHaveLength(2));

    act(() => result.current.setSelectedTeam('舊團體'));
    await waitFor(() => expect(apiClient.getTeamPeople).toHaveBeenCalledWith('sheet', '工作表', '舊團體'));
    act(() => result.current.setSelectedTeam('新團體'));
    await waitFor(() => expect(apiClient.getTeamPeople).toHaveBeenCalledWith('sheet', '工作表', '新團體'));

    await act(async () => {
      resolveOld({ people: ['舊人物'] });
      resolveNew({ people: ['新人物'] });
    });
    await waitFor(() => expect(result.current.people).toEqual(['新人物']));
    expect(result.current.selectedPeople).toEqual(['新人物']);
  });

  it('clears downstream state when the worksheet is disabled or changed', async () => {
    const apiClient = {
      parseSheetOptions: vi.fn().mockResolvedValue({ teams: ['團體'] }),
      getTeamPeople: vi.fn().mockResolvedValue({ people: ['人物'] }),
    };
    const { result, rerender } = renderHook(
      (props) => useTeamPersonFilter({ ...props, apiClient }),
      { initialProps: { source: 'sheet', worksheetName: '工作表', enabled: true } },
    );
    await waitFor(() => expect(result.current.teams).toEqual(['團體']));
    act(() => result.current.setSelectedTeam('團體'));
    await waitFor(() => expect(result.current.people).toEqual(['人物']));

    rerender({ source: 'sheet', worksheetName: '另一張', enabled: false });
    await waitFor(() => {
      expect(result.current.teams).toEqual([]);
      expect(result.current.selectedTeam).toBe('');
      expect(result.current.people).toEqual([]);
    });
  });
});

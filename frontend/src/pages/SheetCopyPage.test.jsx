import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SheetCopyPage from './SheetCopyPage';
import { api } from '../services/api';
import { AccountWorkStateProvider } from '../hooks/useAccountWorkState';

vi.mock('../services/api', () => ({
  api: {
    updateWorkState: vi.fn(),
    getSpreadsheetMetadata: vi.fn(),
    getCopyableSheetTable: vi.fn(),
  },
}));

vi.mock('../components/SheetDataSourcePanel', () => ({ default: () => <div data-testid="sheet-source" /> }));
vi.mock('../components/TeamPersonFilterPanel', () => ({ default: () => <div data-testid="team-person-filter" /> }));
vi.mock('../hooks/useTeamPersonFilter', () => ({
  default: () => ({
    teams: [],
    selectedTeam: '',
    setSelectedTeam: vi.fn(),
    people: [],
    selectedPeople: [],
    setSelectedPeople: vi.fn(),
    loadingTeams: false,
    loadingPeople: false,
    ready: false,
    error: '',
  }),
}));
vi.mock('../hooks/useSharedTeamPersonFilterPersistence', () => ({ default: () => ({}) }));

function renderPage(initialState) {
  return render(
    <AccountWorkStateProvider initialState={initialState}>
      <SheetCopyPage sysSettings={{ shared_team_person_filter: {} }} />
    </AccountWorkStateProvider>,
  );
}

describe('SheetCopyPage work-state persistence', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    api.updateWorkState.mockResolvedValue({ state: {} });
  });

  afterEach(() => vi.useRealTimers());

  it('restores the last display option and saves a changed option once', async () => {
    renderPage({ sheet_copy: { autoCollapse: true, query: 'last search' } });

    const autoCollapse = screen.getByLabelText('自動折疊內容格子');
    expect(autoCollapse).toBeChecked();
    expect(screen.getByLabelText('內容搜尋')).toHaveValue('last search');

    fireEvent.click(autoCollapse);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(450);
    });

    expect(api.updateWorkState).toHaveBeenCalledTimes(1);
    expect(api.updateWorkState).toHaveBeenCalledWith('sheet_copy', {
      spreadsheetId: '',
      worksheetName: '',
      visibleKeys: [],
      query: 'last search',
      autoCollapse: false,
    });
  });
});

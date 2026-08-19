import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GoogleSheetSettingsPage from './GoogleSheetSettingsPage';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: {
    updateSharedSettings: vi.fn(),
  },
}));

vi.mock('../components/Toast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

vi.mock('../components/SourceLinkInput', () => ({
  default: ({ value, onChange }) => <input aria-label="Google Sheet" value={value} onChange={onChange} />,
}));

function renderPage(refreshSettings = vi.fn().mockResolvedValue({})) {
  return render(<GoogleSheetSettingsPage
    sysSettings={{ default_spreadsheet_id: 'old-sheet' }}
    refreshSettings={refreshSettings}
  />);
}

describe('GoogleSheetSettingsPage autosave lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    api.updateSharedSettings.mockResolvedValue({});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('flushes the latest debounced value once when the page unmounts', async () => {
    const refreshSettings = vi.fn().mockResolvedValue({});
    const { unmount } = renderPage(refreshSettings);

    fireEvent.change(screen.getByLabelText('Google Sheet'), { target: { value: 'latest-sheet' } });
    expect(api.updateSharedSettings).not.toHaveBeenCalled();

    unmount();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.updateSharedSettings).toHaveBeenCalledTimes(1);
    expect(api.updateSharedSettings).toHaveBeenCalledWith({ default_spreadsheet_id: 'latest-sheet' });
    expect(refreshSettings).not.toHaveBeenCalled();
  });

  it('does not duplicate an autosave already queued before unmount', async () => {
    let resolveSave;
    api.updateSharedSettings.mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));
    const { unmount } = renderPage();

    fireEvent.change(screen.getByLabelText('Google Sheet'), { target: { value: 'queued-sheet' } });
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.updateSharedSettings).toHaveBeenCalledTimes(1);

    unmount();
    expect(api.updateSharedSettings).toHaveBeenCalledTimes(1);

    resolveSave({});
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  });
});

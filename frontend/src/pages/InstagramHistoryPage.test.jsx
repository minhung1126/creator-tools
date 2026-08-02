import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import { ToastProvider } from '../components/Toast';
import InstagramHistoryPage from './InstagramHistoryPage';

vi.mock('../services/api', () => ({
  api: {
    getInstagramPublishHistory: vi.fn(),
    clearInstagramPublishHistory: vi.fn(),
    deleteInstagramPublishHistory: vi.fn(),
  },
}));

const record = {
  record_id: 'job-1:file-1',
  job_id: 'job-1',
  file_id: 'file-1',
  file_name: 'reel.mp4',
  person: 'A',
  team: 'Team',
  status: 'published',
  published_at: '2026-08-01T09:00:00+00:00',
  media_id: 'media-1',
  drive_moved: true,
  preflight: { width: 1080, height: 1920, duration_seconds: 12 },
};

describe('InstagramHistoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getInstagramPublishHistory.mockResolvedValue({ records: [record] });
    api.clearInstagramPublishHistory.mockResolvedValue({ deleted_count: 1, failed_count: 0 });
    api.deleteInstagramPublishHistory.mockResolvedValue({ drive_restored: true });
  });

  it('loads history and deletes a record after confirmation', async () => {
    render(<ToastProvider><InstagramHistoryPage /></ToastProvider>);

    await waitFor(() => expect(screen.getByText('reel.mp4')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '刪除紀錄並移回來源' }));
    expect(screen.getByText('刪除 Instagram 歷史紀錄')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '刪除紀錄', exact: true }));

    await waitFor(() => expect(api.deleteInstagramPublishHistory).toHaveBeenCalledWith('job-1', 'file-1'));
    expect(screen.queryByText('reel.mp4')).not.toBeInTheDocument();
  });

  it('clears all history after confirmation', async () => {
    api.getInstagramPublishHistory
      .mockResolvedValueOnce({ records: [record] })
      .mockResolvedValueOnce({ records: [] });
    render(<ToastProvider><InstagramHistoryPage /></ToastProvider>);

    await waitFor(() => expect(screen.getByText('reel.mp4')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '清除歷史' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('清除全部 Instagram 歷史紀錄');

    fireEvent.click(screen.getByRole('dialog').querySelector('.btn-danger'));

    await waitFor(() => expect(api.clearInstagramPublishHistory).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('reel.mp4')).not.toBeInTheDocument());
  });
});

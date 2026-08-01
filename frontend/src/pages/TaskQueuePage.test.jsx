import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import TaskQueuePage from './TaskQueuePage';

const activity = vi.hoisted(() => ({
  tasks: [
    { id: 'ig-1', batch_id: 'batch-1', batch_short_code: 'BATCH-1', platform: 'instagram', operation: 'instagram.reels_publish', video_id: 'drive-1', video_title: 'Instagram video', status: 'queued', stage: 'queued', stage_label: '排隊中', progress_percent: 0, retryable: true, sequence_in_batch: 1 },
    { id: 'yt-1', batch_id: 'batch-2', batch_short_code: 'BATCH-2', platform: 'youtube', operation: 'youtube.metadata_update', video_id: 'yt-1', video_title: 'YouTube video', status: 'paused', stage: 'paused', stage_label: '需要處理', progress_percent: 20, retryable: true, sequence_in_batch: 1 },
  ],
  summary: { tasks: { active: 1, paused: 1, failed: 0, completed: 0 }, unread_notification_count: 0 },
  loading: false,
  refreshing: false,
  error: null,
  refresh: vi.fn(),
  cancelTask: vi.fn().mockResolvedValue({}),
  retryTask: vi.fn().mockResolvedValue({}),
  cancelAll: vi.fn().mockResolvedValue({}),
  cancelBatch: vi.fn().mockResolvedValue({}),
  retryBatch: vi.fn().mockResolvedValue({}),
}));

vi.mock('../hooks/useActivityCenter', () => ({ useActivityCenter: () => activity }));

describe('TaskQueuePage', () => {
  it('renders one row per video and filters by platform', () => {
    render(<TaskQueuePage />);
    expect(screen.getAllByText('Instagram video').length).toBeGreaterThan(0);
    expect(screen.getAllByText('YouTube video').length).toBeGreaterThan(0);
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'instagram' } });
    expect(screen.getAllByText('Instagram video').length).toBeGreaterThan(0);
    expect(screen.queryByText('YouTube video')).not.toBeInTheDocument();
  });

  it('confirms cancel-all with both platform and queued/running counts', async () => {
    render(<TaskQueuePage />);
    fireEvent.click(screen.getByRole('button', { name: '取消所有未完成任務' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Instagram 未完成 1 支、YouTube 未完成 1 支');
    expect(screen.getByRole('dialog')).toHaveTextContent('執行中的外部 API 可能已無法阻止');
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '取消所有未完成任務' }));
    await waitFor(() => expect(activity.cancelAll).toHaveBeenCalled());
  });
});

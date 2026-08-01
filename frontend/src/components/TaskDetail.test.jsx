import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import TaskDetail from './TaskDetail';

const task = (status) => ({
  id: `task-${status}`,
  batch_id: 'batch-1',
  batch_short_code: 'BATCH-1',
  platform: 'youtube',
  operation: 'youtube.metadata_update',
  video_id: 'video-1',
  video_title: '測試影片',
  status,
  stage: status,
  stage_label: status,
  progress_percent: 20,
  retryable: false,
});

describe('TaskDetail', () => {
  it('shows a disabled cancellation-in-progress button', () => {
    render(<TaskDetail task={task('cancel_requested')} />);
    const button = screen.getByRole('button', { name: '取消中…' });
    expect(button).toBeDisabled();
    expect(screen.getAllByText('正在取消')).not.toHaveLength(0);
  });

  it('uses the safe queued cancellation copy and calls the handler', () => {
    const onCancel = vi.fn();
    render(<TaskDetail task={task('queued')} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('尚未開始，將立即從隊列移除。');
    fireEvent.click(screen.getByRole('button', { name: '確認取消' }));
    expect(onCancel).toHaveBeenCalledWith(expect.objectContaining({ status: 'queued' }));
  });
});

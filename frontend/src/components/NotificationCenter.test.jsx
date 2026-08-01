import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import NotificationCenter from './NotificationCenter';

const activity = vi.hoisted(() => ({
  notifications: [{ id: 1, event_key: 'one', severity: 'warning', type: 'task_paused', title: '任務已暫停', message: '請確認後重試', task_id: 'task-1', created_at: new Date().toISOString(), read_at: null }],
  unreadCount: 1,
  loading: false,
  error: null,
  refresh: vi.fn(),
  markNotificationRead: vi.fn().mockResolvedValue({}),
  markAllNotificationsRead: vi.fn().mockResolvedValue({}),
}));

vi.mock('../hooks/useActivityCenter', () => ({ useActivityCenter: () => activity }));

describe('NotificationCenter', () => {
  it('keeps unread notifications until clicked and opens their task target', async () => {
    const onOpenTarget = vi.fn();
    const onClose = vi.fn();
    render(<NotificationCenter open onClose={onClose} onOpenTarget={onOpenTarget} />);
    expect(screen.getByRole('tab', { name: /未讀/ })).toHaveAttribute('aria-selected', 'false');
    fireEvent.click(screen.getByRole('button', { name: /任務已暫停/ }));
    expect(activity.markNotificationRead).toHaveBeenCalledWith(1);
    await waitFor(() => expect(onOpenTarget).toHaveBeenCalledWith('task-1', undefined));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('supports marking every notification read', () => {
    render(<NotificationCenter open onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '全部標記已讀' }));
    expect(activity.markAllNotificationsRead).toHaveBeenCalled();
  });
});

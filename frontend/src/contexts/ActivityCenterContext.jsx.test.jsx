import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ToastProvider } from '../components/Toast';
import { ActivityCenterProvider } from './ActivityCenterContext';
import { api } from '../services/api';
import { useActivityCenter } from '../hooks/useActivityCenter';

function Probe() {
  const { activeCount, unreadCount } = useActivityCenter();
  return <div>{activeCount}:{unreadCount}</div>;
}

function TaskCountProbe() {
  const { tasks } = useActivityCenter();
  return <div>tasks:{tasks.length}</div>;
}

describe('ActivityCenterProvider', () => {
  it('loads the durable summary and notification count', async () => {
    vi.spyOn(api, 'getActivitySummary').mockResolvedValue({ tasks: { active: 2 } });
    vi.spyOn(api, 'getTasks').mockResolvedValue({ items: [] });
    vi.spyOn(api, 'getNotifications').mockResolvedValue({ items: [{ event_key: 'existing', read_at: null }], unread_count: 3 });
    render(<ToastProvider><ActivityCenterProvider><Probe /></ActivityCenterProvider></ToastProvider>);
    await waitFor(() => expect(screen.getByText('2:3')).toBeInTheDocument());
  });

  it('loads every persisted task page instead of hiding tasks after the first 100', async () => {
    vi.spyOn(api, 'getActivitySummary').mockResolvedValue({ tasks: { active: 0 } });
    vi.spyOn(api, 'getTasks').mockImplementation(({ offset }) => Promise.resolve(
      offset === 0
        ? { items: Array.from({ length: 100 }, (_, index) => ({ id: `task-${index}` })), total: 101 }
        : { items: [{ id: 'task-100' }], total: 101 },
    ));
    vi.spyOn(api, 'getNotifications').mockResolvedValue({ items: [], unread_count: 0 });

    render(<ToastProvider><ActivityCenterProvider><TaskCountProbe /></ActivityCenterProvider></ToastProvider>);

    await waitFor(() => expect(screen.getByText('tasks:101')).toBeInTheDocument());
    expect(api.getTasks).toHaveBeenCalledWith({ offset: 100, limit: 100 });
  });
});

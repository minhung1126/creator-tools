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

describe('ActivityCenterProvider', () => {
  it('loads the durable summary and notification count', async () => {
    vi.spyOn(api, 'getActivitySummary').mockResolvedValue({ tasks: { active: 2 } });
    vi.spyOn(api, 'getTasks').mockResolvedValue({ items: [] });
    vi.spyOn(api, 'getNotifications').mockResolvedValue({ items: [{ event_key: 'existing', read_at: null }], unread_count: 3 });
    render(<ToastProvider><ActivityCenterProvider><Probe /></ActivityCenterProvider></ToastProvider>);
    await waitFor(() => expect(screen.getByText('2:3')).toBeInTheDocument());
  });
});

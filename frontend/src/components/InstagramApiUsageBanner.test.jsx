import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import InstagramApiUsageBanner from './InstagramApiUsageBanner';

vi.mock('../services/api', () => ({
  api: {
    getInstagramApiUsage: vi.fn(),
  },
}));

describe('InstagramApiUsageBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getInstagramApiUsage.mockResolvedValue({
      usage_percent: 18,
      requests_today: 4,
      updated_at: '2026-08-01T10:00:00+00:00',
      meta_usage: {
        available: true,
        call_volume: 18,
        cpu_time: 3,
        total_time: 5,
        observed_at: '2026-08-01T10:00:00+00:00',
      },
      methods: [{ endpoint: 'POST create media container', calls: 2 }],
      note: 'usage note',
    });
  });

  it('renders Meta usage metrics and local request counts', async () => {
    render(<InstagramApiUsageBanner />);

    await waitFor(() => expect(screen.getByText('Instagram API 使用情況')).toBeInTheDocument());
    expect(screen.getByText('18% / 100%')).toBeInTheDocument();
    expect(screen.getByText(/本系統今日請求 4 次/)).toBeInTheDocument();
    expect(screen.getByText(/呼叫量 18%/)).toBeInTheDocument();
    expect(screen.getByText(/POST create media container: 2 次/)).toBeInTheDocument();
  });
});

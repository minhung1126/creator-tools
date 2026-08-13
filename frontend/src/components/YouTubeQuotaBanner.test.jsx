import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import YouTubeQuotaBanner from './YouTubeQuotaBanner';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: { getYoutubeQuotaUsage: vi.fn() },
}));

const usage = (state = 'normal') => ({
  state,
  official_default_limit: 10000,
  configured_project_limit: 12000,
  estimated_used_units: state === 'confirmed_exhausted' ? 8940 : 3820,
  estimated_remaining_units: 8060,
  safety_buffer_units: 1000,
  policy_cap_units: 11000,
  effective_available_units: state === 'confirmed_exhausted' ? 0 : 7180,
  confirmed_by_google: state === 'confirmed_exhausted',
  reset_at: '2026-08-03T00:00:00-07:00',
  reset_timezone: 'America/Los_Angeles',
  methods: [{ method: 'videos.update', calls: 2, cost_per_call: 50, units: 100 }],
  quota_rules_verified_at: '2026-08-02',
  note: '本數字只統計 Creator Tools',
});

describe('YouTubeQuotaBanner', () => {
  beforeEach(() => vi.clearAllMocks());

  it('separates project limit, safety buffer, effective units and method costs', async () => {
    api.getYoutubeQuotaUsage.mockResolvedValue(usage());
    render(<YouTubeQuotaBanner />);
    await waitFor(() => expect(screen.getByText(/系統可用 7,180 units/)).toBeInTheDocument());
    expect(screen.getByText(/官方預設 10,000/)).toBeInTheDocument();
    expect(screen.getByText(/project 設定 12,000/)).toBeInTheDocument();
    expect(screen.getByText(/安全保留 1,000/)).toBeInTheDocument();
    expect(screen.getByText(/videos.update: 2 次/)).toBeInTheDocument();
    expect(screen.getByText(/官方重設/)).toHaveTextContent('本地時間');
  });

  it('shows confirmed exhaustion as blocked with zero effective availability', async () => {
    api.getYoutubeQuotaUsage.mockResolvedValue(usage('confirmed_exhausted'));
    render(<YouTubeQuotaBanner />);
    await waitFor(() => expect(screen.getByText('Google 已確認 `quotaExceeded`；系統已停止新的 YouTube request，直到官方重設。Google Cloud project 的其他應用程式也可能消耗額度。')).toBeInTheDocument());
    expect(screen.getByText(/系統可用 0 units/)).toBeInTheDocument();
  });

  it('loads the selected secondary slot ledger', async () => {
    api.getYoutubeQuotaUsage.mockResolvedValue(usage());
    render(<YouTubeQuotaBanner activeSlot="secondary" />);
    await waitFor(() => expect(api.getYoutubeQuotaUsage).toHaveBeenCalledWith('secondary'));
    expect(screen.getByLabelText('YouTube quota slot')).toHaveValue('secondary');
  });
});

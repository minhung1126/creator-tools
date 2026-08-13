import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    await waitFor(() => expect(screen.getByText(/系統可用 7,180 單位/)).toBeInTheDocument());
    expect(screen.getByText(/官方預設 10,000/)).toBeInTheDocument();
    expect(screen.getByText(/專案設定 12,000/)).toBeInTheDocument();
    expect(screen.getByText(/安全預留 1,000/)).toBeInTheDocument();
    expect(screen.getByText(/videos.update: 2 次/)).toBeInTheDocument();
    expect(screen.getByText(/官方重設/)).toHaveTextContent('本地時間');
  });

  it('shows confirmed exhaustion as blocked with zero effective availability', async () => {
    api.getYoutubeQuotaUsage.mockResolvedValue(usage('confirmed_exhausted'));
    render(<YouTubeQuotaBanner />);
    await waitFor(() => expect(screen.getByText('Google 已確認 `quotaExceeded`；系統已停止新的 YouTube 請求，直到官方重設。')).toBeInTheDocument());
    expect(screen.getByText(/系統可用 0 單位/)).toBeInTheDocument();
  });

  it('loads the selected secondary slot ledger', async () => {
    api.getYoutubeQuotaUsage.mockResolvedValue(usage());
    render(<YouTubeQuotaBanner activeSlot="secondary" availableSlots={['primary', 'secondary']} />);
    await waitFor(() => expect(api.getYoutubeQuotaUsage).toHaveBeenCalledWith('secondary'));
    expect(screen.getByLabelText('YouTube 授權組合')).toHaveValue('secondary');
  });

  it('does not show the previous slot while the next slot is loading', async () => {
    let resolveSecondary;
    api.getYoutubeQuotaUsage
      .mockResolvedValueOnce(usage())
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecondary = resolve; }));
    render(<YouTubeQuotaBanner availableSlots={['primary', 'secondary']} />);
    await waitFor(() => expect(screen.getByText(/系統可用 7,180 單位/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('YouTube 授權組合'), { target: { value: 'secondary' } });
    await waitFor(() => expect(screen.getByText(/正在更新次要授權組合資料/)).toBeInTheDocument());
    expect(screen.queryByText(/系統可用 7,180 單位/)).not.toBeInTheDocument();

    resolveSecondary(usage('warning'));
    await waitFor(() => expect(screen.getByText('接近安全上限')).toBeInTheDocument());
  });

  it('does not reuse the previous slot data after a refresh failure', async () => {
    api.getYoutubeQuotaUsage
      .mockResolvedValueOnce(usage())
      .mockRejectedValueOnce(new Error('暫時無法連線'));
    render(<YouTubeQuotaBanner />);
    await waitFor(() => expect(screen.getByText(/系統可用 7,180 單位/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /更新/ }));
    await waitFor(() => expect(screen.getByText('主要授權組合配額更新失敗')).toBeInTheDocument());
    expect(screen.queryByText(/系統可用 7,180 單位/)).not.toBeInTheDocument();
    expect(screen.getByText(/資料已過期；最後成功更新/)).toBeInTheDocument();
  });
});

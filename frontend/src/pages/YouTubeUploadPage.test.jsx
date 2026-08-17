import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import YouTubeUploadPage, { getYoutubeUploadQuotaDecision } from './YouTubeUploadPage';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: {
    previewYoutubeDriveUpload: vi.fn(),
    createYoutubeDriveUploadJob: vi.fn(),
    getYoutubeDriveUploadJob: vi.fn(),
    getAuthUrl: vi.fn(),
  },
}));

vi.mock('../components/Toast', () => ({
  useToast: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }),
}));

vi.mock('../components/SourceLinkInput', () => ({
  default: ({ id, value, onChange, sourceType, ...props }) => <input id={id} value={value} onChange={onChange} {...props} />,
}));

const preview = (overrides = {}) => ({
  status: 'preview_ready',
  source: { id: 'drive-folder', name: '影片資料夾' },
  playlist: { id: 'playlist-1' },
  youtube: { slot: 'secondary', slot_reason: 'auto_secondary_quota_insufficient' },
  preview_token: 'preview-token',
  preview_snapshot: { youtube_slot: 'secondary' },
  summary: { total: 2, uploadable: 2 },
  items: [{ file_id: 'file-1', sequence: 1, name: 'video.mp4', title: 'Video' }],
  quota: {
    can_complete: true,
    estimated_units: { general: 101, video_uploads: 2, total: 103 },
    general: {
      projected_units: 100,
      projected_with_preview_reads: 101,
      effective_available_units: 100,
      limit: 10000,
    },
    video_uploads: { projected_units: 2, effective_available_units: 98, limit: 100 },
  },
  ...overrides,
});

function renderPage() {
  return render(<YouTubeUploadPage
    authUser={{ sub: 'user-1', google_scopes: { drive_readonly: true } }}
    sysSettings={{ default_playlist_id: 'playlist-1' }}
  />);
}

describe('YouTubeUploadPage quota admission', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('does not treat a completed preview as permission to create a job', async () => {
    api.previewYoutubeDriveUpload.mockResolvedValue(preview({
      quota: {
        ...preview().quota,
        can_complete: false,
        general: {
          ...preview().quota.general,
          projected_units: 101,
          remaining_required: 101,
          projected_full_workflow: 102,
          effective_available_units: 100,
        },
      },
    }));
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));

    await waitFor(() => expect(screen.getByText('預覽結果')).toBeInTheDocument());
    expect(screen.getByText('預覽已完成，但目前不可建立工作')).toBeInTheDocument();
    expect(screen.getByText(/General 配額不足/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '確認開始背景上傳' })).toBeDisabled();
    expect(screen.getByText('實際 slot：次要授權組合')).toBeInTheDocument();
    expect(screen.getByText('auto_secondary_quota_insufficient')).toBeInTheDocument();
  });

  it('enables creation for the stage-aware backend shape at the exact remaining boundary', async () => {
    api.previewYoutubeDriveUpload.mockResolvedValue(preview({
      youtube: { slot: 'primary', slot_reason: 'preview_pinned_slot' },
      preview_snapshot: { youtube_slot: 'primary' },
      quota: {
        can_complete: true,
        estimated_units: { general: 102, video_uploads: 2, total: 104 },
        general: {
          projected_units: 101,
          remaining_required: 101,
          projected_full_workflow: 102,
          already_spent: 1,
          effective_available_units: 101,
          limit: 10000,
        },
        video_uploads: {
          projected_units: 2,
          remaining_required: 2,
          projected_full_workflow: 2,
          already_spent: 0,
          effective_available_units: 2,
          limit: 100,
        },
      },
    }));
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));

    await waitFor(() => expect(screen.getByRole('button', { name: '確認開始背景上傳' })).toBeEnabled());
    expect(screen.getByText(/建立前仍會重新檢查/)).toBeInTheDocument();
    expect(screen.getByText(/完整流程 102/)).toBeInTheDocument();
  });

  it('uses the backend create decision when it differs from preview can_complete', async () => {
    const response = preview({
      quota: {
        ...preview().quota,
        can_start: false,
        can_create: false,
        can_start_reason: '建立前驗證讀取不足',
        general: { ...preview().quota.general, effective_available_units: 1000 },
      },
    });
    api.previewYoutubeDriveUpload.mockResolvedValue(response);
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));

    await waitFor(() => expect(screen.getByText(/建立前驗證讀取不足/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: '確認開始背景上傳' })).toBeDisabled();
  });

  it('does not enable job creation when preview has zero uploadable items', async () => {
    api.previewYoutubeDriveUpload.mockResolvedValue(preview({ summary: { total: 2, uploadable: 0, skipped: 2 } }));
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));

    await waitFor(() => expect(screen.getByText(/沒有可上傳的項目/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: '確認開始背景上傳' })).toBeDisabled();
  });

  it('keeps a pinned backend slot and shows the separate quota costs', async () => {
    api.previewYoutubeDriveUpload.mockResolvedValue(preview({
      youtube: { slot: 'primary', slot_reason: 'preview_pinned_slot' },
      preview_snapshot: { youtube_slot: 'primary' },
      quota: {
        ...preview().quota,
        preview_read: { general: 1, video_uploads: 0 },
        job_required: { general: 100, video_uploads: 2 },
        total: { general: 101, video_uploads: 2 },
        can_start: true,
      },
    }));
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));

    await waitFor(() => expect(screen.getByText('實際 slot：主要授權組合')).toBeInTheDocument());
    expect(screen.getByText('preview_pinned_slot')).toBeInTheDocument();
    expect(screen.getByText(/預覽讀取 1 · 完整流程 101/)).toBeInTheDocument();
    expect(screen.getByText(/預覽已驗證，但建立前仍會重新檢查/)).toBeInTheDocument();
  });

  it('shows confirmed exhaustion and asks for a fresh preview', async () => {
    api.previewYoutubeDriveUpload.mockResolvedValue(preview({
      quota: {
        ...preview().quota,
        confirmed_by_google: true,
        state: 'confirmed_exhausted',
        general: { ...preview().quota.general, effective_available_units: 0, reset_at: '2026-08-19T00:00:00Z' },
      },
    }));
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));

    await waitFor(() => expect(screen.getByText('Google 已確認 quota 耗盡')).toBeInTheDocument());
    expect(screen.getByText(/請重新解析 Drive 內容/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '確認開始背景上傳' })).toBeDisabled();
  });

  it('clears a stale preview after the backend rejects job creation', async () => {
    api.previewYoutubeDriveUpload.mockResolvedValue(preview({
      quota: {
        ...preview().quota,
        create_can_execute: true,
        general: { ...preview().quota.general, effective_available_units: 101 },
      },
    }));
    api.createYoutubeDriveUploadJob.mockRejectedValue({ code: 'stale_preview', status: 409, message: '預覽已過期' });
    renderPage();

    fireEvent.change(screen.getByLabelText('Google Drive ID／網址'), { target: { value: 'drive-folder' } });
    fireEvent.click(screen.getByRole('button', { name: '解析 Drive 內容' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '確認開始背景上傳' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: '確認開始背景上傳' }));
    await waitFor(() => expect(screen.getByText('請重新預覽後再建立工作')).toBeInTheDocument());
    expect(screen.queryByText('預覽結果')).not.toBeInTheDocument();
  });

  it('keeps preview and create eligibility separate in the normalized decision', () => {
    const decision = getYoutubeUploadQuotaDecision(preview({
      preview_can_execute: true,
      create_can_execute: false,
      quota: { ...preview().quota, can_complete: true },
    }));
    expect(decision.previewCanExecute).toBe(true);
    expect(decision.canCreate).toBe(false);
  });
});

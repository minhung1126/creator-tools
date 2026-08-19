import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BatchUpdatePage, { buildBatchPreview } from './BatchUpdatePage';

const mocks = vi.hoisted(() => ({
  api: {
    getYoutubeDraftSettings: vi.fn(),
    updateYoutubeDraftSettings: vi.fn(),
    getSpreadsheetMetadata: vi.fn(),
    getRandomMemberPreview: vi.fn(),
    getPlaylistVideos: vi.fn(),
    getBatchPreview: vi.fn(),
    estimateYoutubeQuota: vi.fn(),
    batchUpdateMetadata: vi.fn(),
  },
  toast: {
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
  },
  saveWorkState: vi.fn(),
  resetSelection: vi.fn(),
  teams: ['團體 A'],
  people: ['人物甲'],
  selectedPeople: ['人物甲'],
  setSelectedTeam: vi.fn(),
  setSelectedPeople: vi.fn(),
}));

vi.mock('../services/api', () => ({ api: mocks.api }));
vi.mock('../components/Toast', () => ({ useToast: () => mocks.toast }));
vi.mock('../hooks/useAccountWorkState', () => ({
  default: () => ({ value: {}, error: '', save: mocks.saveWorkState }),
}));
vi.mock('../hooks/useTeamPersonFilter', () => ({
  default: () => ({
    teams: mocks.teams,
    selectedTeam: '團體 A',
    setSelectedTeam: mocks.setSelectedTeam,
    people: mocks.people,
    selectedPeople: mocks.selectedPeople,
    setSelectedPeople: mocks.setSelectedPeople,
    loadingTeams: false,
    loadingPeople: false,
    ready: true,
    error: '',
    resetSelection: mocks.resetSelection,
  }),
}));
vi.mock('../hooks/useSharedTeamPersonFilterPersistence', () => ({
  default: () => ({ ready: true }),
}));
vi.mock('../utils/teamPersonFilterStorage', () => ({
  normalizeTeamPersonFilter: (value) => value,
  readSharedTeamPersonFilter: () => ({ exists: false, team: '', selectedPeople: [] }),
}));
vi.mock('../components/SheetDataSourcePanel', () => ({
  default: ({ children }) => <div>{children}</div>,
}));
vi.mock('../components/SourceLinkInput', () => ({
  default: ({ id, value, onChange, sourceType: _sourceType, ...props }) => <input id={id} value={value || ''} onChange={onChange} {...props} />,
}));
vi.mock('../components/TeamPersonFilterPanel', () => ({ default: () => null }));
vi.mock('../components/ThumbnailDialog', () => ({ default: () => null }));

const authUser = {
  sub: 'owner-1',
  youtube: {
    active_slot: 'primary',
    slots: {
      primary: { authenticated: true },
    },
  },
};

const videoOne = {
  video_id: 'video-1',
  title: '舊標題一',
  description: '舊描述一\n第二行',
};

const videoTwo = {
  video_id: 'video-2',
  title: '保留標題',
  description: '保留描述',
};

function renderPage() {
  return render(
    <BatchUpdatePage
      authUser={authUser}
      sysSettings={{ default_spreadsheet_id: 'sheet-a', default_playlist_id: 'playlist-a' }}
      videoType="Video"
    />,
  );
}

describe('BatchUpdatePage preview and confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.api.getYoutubeDraftSettings.mockResolvedValue({});
    mocks.api.getSpreadsheetMetadata.mockResolvedValue({
      worksheets: [{ title: 'Youtube Video', columns: ['Youtube Title', 'Youtube Description'] }],
    });
    mocks.api.getRandomMemberPreview.mockResolvedValue({ person: '人物甲', values: {} });
    mocks.api.getPlaylistVideos.mockResolvedValue({ videos: [videoOne, videoTwo], source: 'youtube-api' });
    mocks.api.getBatchPreview.mockResolvedValue({
      preview_token: 'preview-token',
      preview_snapshot: { youtube_slot: 'primary' },
      plan: [
        {
          videoId: 'video-1',
          currentTitle: '舊標題一',
          currentDescription: '舊描述一\n第二行',
          newTitle: '新標題一',
          newDescription: '新描述一\n第二行',
          person: '人物甲',
          status: 'ready',
          willUpdate: true,
        },
        {
          videoId: 'video-2',
          currentTitle: '保留標題',
          currentDescription: '保留描述',
          newTitle: '',
          newDescription: '',
          person: '不編輯',
          status: 'skipped',
          reason: '未指定人物',
          willUpdate: false,
        },
      ],
    });
    mocks.api.estimateYoutubeQuota.mockResolvedValue({
      projected_units: 100,
      effective_available_units: 200,
      can_complete_today: true,
    });
    mocks.api.batchUpdateMetadata.mockResolvedValue({
      completed: true,
      total_count: 2,
      succeeded_count: 1,
      skipped_count: 1,
      failed_count: 0,
    });
  });

  it('keeps the preview builder explicit about unchanged and skipped items', () => {
    const preview = buildBatchPreview({
      videos: [videoOne, videoTwo],
      sheetRows: [
        { team: '團體 A', person: '人物甲', cells: ['舊標題一', '舊描述一\n第二行'] },
      ],
      sheetColumns: [
        { label: '標題', key: 'title', index: 0 },
        { label: '描述', key: 'description', index: 1 },
      ],
      team: '團體 A',
      titleColumn: '標題',
      descriptionColumn: '描述',
      assignments: { 'video-1': '人物甲', 'video-2': '不編輯' },
    });

    expect(preview[0]).toMatchObject({ status: 'unchanged', willUpdate: false, reason: '標題與描述沒有變更' });
    expect(preview[1]).toMatchObject({ status: 'skipped', reason: '未指定人物' });
  });

  it('shows current and next content, skip reason, and a structured confirmation summary', async () => {
    const { container } = renderPage();
    const loadButton = await screen.findByRole('button', { name: '讀取 Video 草稿影片' });
    fireEvent.click(loadButton);
    await screen.findByText('舊標題一');

    const assignmentSelect = container.querySelector('.video-card-assignment select');
    fireEvent.change(assignmentSelect, { target: { value: '人物甲' } });
    fireEvent.click(screen.getByRole('button', { name: '檢查並更新標題與描述' }));

    const dialog = await screen.findByRole('dialog', { name: '確認批次更新 1 支影片' });
    expect(await screen.findByText('批次更新預覽')).toBeInTheDocument();
    const previewPanel = screen.getByRole('region', { name: '完整批次變更預覽' });
    expect(within(previewPanel).getAllByText('目前內容')).toHaveLength(2);
    expect(within(previewPanel).getAllByText('更新後內容')).toHaveLength(2);
    expect(within(previewPanel).getAllByText('舊標題一').length).toBeGreaterThan(0);
    expect(within(previewPanel).getByText('新標題一')).toBeInTheDocument();
    expect(within(previewPanel).getByText('原因：未指定人物')).toBeInTheDocument();
    expect(within(dialog).getByText('將更新')).toBeInTheDocument();
    expect(within(dialog).getByText('略過')).toBeInTheDocument();
    expect(within(dialog).getByText('100 單位')).toBeInTheDocument();
    expect(within(dialog).getByText('200 單位')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: '開始批次更新' }));
    await waitFor(() => expect(mocks.api.batchUpdateMetadata).toHaveBeenCalledTimes(1));
    expect(mocks.api.batchUpdateMetadata).toHaveBeenCalledWith(expect.objectContaining({
      previewToken: 'preview-token',
      assignments: [
        { video_id: 'video-1', person: '人物甲' },
        { video_id: 'video-2', person: '不編輯' },
      ],
    }));
  });
});

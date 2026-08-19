import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import YouTubeSettingsLayout from './YouTubeSettingsLayout';
import YoutubeConnectionsPage from '../pages/YoutubeConnectionsPage';
import { PATHS } from '../routes/paths';

vi.mock('../services/api', () => ({
  api: {
    updateYoutubeQuota: vi.fn(),
    updateYoutubePlaylist: vi.fn(),
    updateYoutubeRoutingMode: vi.fn(),
    getYoutubeAuthUrl: vi.fn(),
    activateYoutubeSlot: vi.fn(),
    disconnectYoutube: vi.fn(),
  },
  normalizeYoutubePlaylistInput: (value) => String(value || '').trim(),
}));

vi.mock('../components/Toast', () => ({
  useToast: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }),
}));

vi.mock('../components/SourceLinkInput', () => ({
  default: ({ value, onChange }) => <input value={value} onChange={onChange} />,
}));

describe('YouTubeSettingsLayout', () => {
  it('keeps the shared page title as the only YouTube settings h1', () => {
    render(
      <MemoryRouter initialEntries={[PATHS.youtubeConnections]}>
        <Routes>
          <Route path="/youtube/settings/*" element={<YouTubeSettingsLayout />}>
            <Route path="connections" element={<YoutubeConnectionsPage
              authUser={{ youtube: { slots: { primary: {}, secondary: {} } } }}
              sysSettings={{}}
              refreshSettings={vi.fn()}
              refreshAuthUser={vi.fn()}
            />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getAllByRole('heading', { level: 1, name: 'YouTube 設定' })).toHaveLength(1);
    expect(screen.getByRole('navigation', { name: 'YouTube 設定子導覽' })).toBeInTheDocument();
  });
});

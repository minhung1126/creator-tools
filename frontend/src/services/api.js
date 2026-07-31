const API_BASE = '/api/v1';

async function request(endpoint, options = {}) {
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  const response = await fetch(`${API_BASE}${endpoint}`, config);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || data.message || `Request failed with status ${response.status}`);
  }

  return data;
}

export const api = {
  // Auth
  getAuthConfig: () => request('/auth/config'),
  getAuthUrl: () => request('/auth/url'),
  getUserStatus: () => request('/auth/user'),
  logout: () => request('/auth/logout', { method: 'POST' }),

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (payload) => request('/settings', { method: 'POST', body: JSON.stringify(payload) }),

  // Sheets
  parseSheetOptions: (spreadsheetUrlOrId) =>
    request('/sheets/parse-options', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId }) }),

  getTeamPeople: (spreadsheetUrlOrId, videoType, team) =>
    request('/sheets/people', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, video_type: videoType, team }) }),

  // YouTube
  getPlaylistVideos: (playlistId) =>
    request('/youtube/playlist-items', { method: 'POST', body: JSON.stringify({ playlist_id: playlistId }) }),

  batchUpdateMetadata: (spreadsheetUrlOrId, playlistId, videoType, team, assignments) =>
    request('/youtube/batch-update', {
      method: 'POST',
      body: JSON.stringify({
        spreadsheet_url_or_id: spreadsheetUrlOrId,
        playlist_id: playlistId,
        video_type: videoType,
        team,
        assignments
      })
    }),

  publishAndCleanup: (playlistId) =>
    request('/youtube/publish-and-cleanup', { method: 'POST', body: JSON.stringify({ playlist_id: playlistId }) })
};

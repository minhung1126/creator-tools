const API_BASE = '/api/v1';

async function request(endpoint, options = {}) {
  const config = { headers: { 'Content-Type': 'application/json', ...options.headers }, ...options };
  const response = await fetch(`${API_BASE}${endpoint}`, config);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.message || `Request failed with status ${response.status}`);
  return data;
}

export const api = {
  getAuthConfig: () => request('/auth/config'),
  getAuthUrl: () => request('/auth/url'),
  getUserStatus: () => request('/auth/user'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  getSettings: () => request('/settings'),
  updateSettings: (payload) => request('/settings', { method: 'POST', body: JSON.stringify(payload) }),
  getSharedSettings: () => request('/settings/shared'),
  updateSharedSettings: (payload) => request('/settings/shared', { method: 'PUT', body: JSON.stringify(payload) }),
  getYoutubeSettings: () => request('/settings/youtube'),
  updateYoutubeSettings: (payload) => request('/settings/youtube', { method: 'PUT', body: JSON.stringify(payload) }),
  getYoutubeDraftSettings: () => request('/settings/youtube-drafts'),
  updateYoutubeDraftSettings: (videoType, config) => request('/settings/youtube-drafts', { method: 'PUT', body: JSON.stringify({ video_type: videoType, config }) }),
  getSpreadsheetMetadata: (spreadsheetUrlOrId) => request('/sheets/metadata', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId }) }),
  parseSheetOptions: (spreadsheetUrlOrId, worksheetName) => request('/sheets/parse-options', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName }) }),
  getTeamPeople: (spreadsheetUrlOrId, worksheetName, team) => request('/sheets/people', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName, team }) }),
  getRandomMemberPreview: (spreadsheetUrlOrId, worksheetName, team, columns) => request('/sheets/random-member-preview', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName, team, columns }) }),
  getCopyableSheetTable: (spreadsheetUrlOrId, worksheetName) => request('/sheets/copy-table', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName }) }),
  getYoutubeQuotaUsage: () => request('/youtube/quota-usage'),
  getPlaylistVideos: (playlistId) => request('/youtube/playlist-items', { method: 'POST', body: JSON.stringify({ playlist_id: playlistId }) }),
  batchUpdateMetadata: ({ spreadsheetUrlOrId, playlistId, videoType, worksheetName, titleColumn, descriptionColumn, team, assignments }) => request('/youtube/batch-update', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, playlist_id: playlistId, video_type: videoType, worksheet_name: worksheetName, title_column: titleColumn, description_column: descriptionColumn, team, assignments }) }),
  publishAndCleanup: (playlistId) => request('/youtube/publish-and-cleanup', { method: 'POST', body: JSON.stringify({ playlist_id: playlistId }) }),
  getInstagramAuthUrl: () => request('/instagram/auth/url'),
  getInstagramAuthStatus: () => request('/instagram/auth/status'),
  refreshInstagramAuth: () => request('/instagram/auth/refresh', { method: 'POST' }),
  disconnectInstagram: () => request('/instagram/auth/connection', { method: 'DELETE' }),
  getInstagramSettings: () => request('/instagram/settings'),
  updateInstagramSettings: (payload) => request('/instagram/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  getInstagramConnectionStatus: () => request('/instagram/connection-status'),
  testInstagramR2: () => request('/instagram/r2/test', { method: 'POST' }),
  getInstagramDriveVideos: (folderUrlOrId) => request('/instagram/drive-videos', { method: 'POST', body: JSON.stringify({ folder_url_or_id: folderUrlOrId }) }),
  createInstagramPublishJob: (payload) => request('/instagram/publish-jobs', { method: 'POST', body: JSON.stringify(payload) }),
  getInstagramPublishJob: (jobId) => request(`/instagram/publish-jobs/${encodeURIComponent(jobId)}`),
  retryInstagramPublishJob: (jobId) => request(`/instagram/publish-jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' }),
};

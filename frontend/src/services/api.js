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
  getSystemInfo: () => request('/settings/system'),
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
  getInstagramApiUsage: () => request('/instagram/api-usage'),
  getInstagramConnectionStatus: () => request('/instagram/connection-status'),
  testInstagramR2: () => request('/instagram/r2/test', { method: 'POST' }),
  getInstagramDriveVideos: (folderUrlOrId) => request('/instagram/drive-videos', { method: 'POST', body: JSON.stringify({ folder_url_or_id: folderUrlOrId }) }),
  getInstagramPublishHistory: () => request('/instagram/publish-history'),
  deleteInstagramPublishHistory: (jobId, fileId) => request(`/instagram/publish-history/${encodeURIComponent(jobId)}/${encodeURIComponent(fileId)}`, { method: 'DELETE' }),
  createInstagramPublishJob: (payload) => request('/instagram/publish-jobs', { method: 'POST', body: JSON.stringify(payload) }),
  stopInstagramBlockingJobs: (jobId) => request(`/instagram/publish-jobs/${encodeURIComponent(jobId)}/stop-blocking-jobs`, { method: 'POST' }),
  getActivitySummary: () => request('/activity-summary'),
  getTasks: (params = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value);
    });
    return request(`/tasks${query.toString() ? `?${query.toString()}` : ''}`);
  },
  getTask: (taskId) => request(`/tasks/${encodeURIComponent(taskId)}`),
  retryTask: (taskId) => request(`/tasks/${encodeURIComponent(taskId)}/retry`, { method: 'POST' }),
  cancelTask: (taskId) => request(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' }),
  cancelAllTasks: () => request('/tasks/cancel-all', { method: 'POST' }),
  getTaskBatches: (params = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value);
    });
    return request(`/task-batches${query.toString() ? `?${query.toString()}` : ''}`);
  },
  getTaskBatch: (batchId) => request(`/task-batches/${encodeURIComponent(batchId)}`),
  retryTaskBatch: (batchId) => request(`/task-batches/${encodeURIComponent(batchId)}/retry`, { method: 'POST' }),
  cancelTaskBatch: (batchId) => request(`/task-batches/${encodeURIComponent(batchId)}/cancel`, { method: 'POST' }),
  getNotifications: ({ unreadOnly = false, offset = 0, limit = 50 } = {}) => request(`/notifications?unread_only=${unreadOnly ? 'true' : 'false'}&offset=${offset}&limit=${limit}`),
  markNotificationRead: (notificationId) => request(`/notifications/${encodeURIComponent(notificationId)}`, { method: 'PATCH', body: JSON.stringify({ read: true }) }),
  markAllNotificationsRead: () => request('/notifications/read-all', { method: 'POST' }),
};

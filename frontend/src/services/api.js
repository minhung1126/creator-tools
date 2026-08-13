const API_BASE = '/api/v1';
const DEFAULT_TIMEOUT_MS = 45_000;
const YOUTUBE_WORKFLOW_TIMEOUT_MS = 10 * 60_000;

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'request_failed', details = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function responseMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message.trim()) return detail.message;
  if (typeof data?.message === 'string' && data.message.trim()) return data.message;
  if (status === 401) return '登入已逾時，請重新登入後再試。';
  if (status === 403) return '目前帳號沒有執行此操作的權限。';
  if (status === 429) return '服務目前忙碌或已達 API 用量限制，請稍後再試。';
  if (status >= 500) return '伺服器暫時無法處理，請稍後按「重試」。';
  return `操作失敗（HTTP ${status}），請重試。`;
}

async function request(endpoint, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const config = {
    ...fetchOptions,
    headers: { 'Content-Type': 'application/json', ...fetchOptions.headers },
    signal: controller.signal,
  };
  let response;
  try {
    response = await fetch(`${API_BASE}${endpoint}`, config);
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new ApiError('連線逾時，請確認網路後按「重試」。', { code: 'timeout' });
    }
    throw new ApiError('目前無法連線到 Creator Tools，請確認服務與網路後重試。', { code: 'network_error' });
  } finally {
    window.clearTimeout(timeout);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent('creator-tools:session-expired'));
    }
    throw new ApiError(responseMessage(data, response.status), {
      status: response.status,
      code: data?.detail?.code || (response.status === 401 ? 'session_expired' : 'request_failed'),
      details: data?.detail && typeof data.detail === 'object' ? data.detail : null,
    });
  }
  return data;
}

export const api = {
  getAuthConfig: () => request('/auth/config'),
  getAuthUrl: () => request('/auth/url'),
  getYoutubeAuthUrl: (slot = 'primary') => request(`/auth/youtube/${encodeURIComponent(slot)}/url`),
  disconnectYoutube: (slot = 'primary', { confirm = false } = {}) => request(`/auth/youtube/${encodeURIComponent(slot)}/disconnect${confirm ? '?confirm=true' : ''}`, { method: 'POST' }),
  activateYoutubeSlot: (slot) => request(`/auth/youtube/${encodeURIComponent(slot)}/activate`, { method: 'POST' }),
  getUserStatus: () => request('/auth/user'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  getSystemInfo: () => request('/settings/system'),
  getSharedSettings: () => request('/settings/shared'),
  updateSharedSettings: (payload) => request('/settings/shared', { method: 'PUT', body: JSON.stringify(payload) }),
  getYoutubeSettings: () => request('/settings/youtube'),
  updateYoutubeSettings: (payload) => request('/settings/youtube', { method: 'PUT', body: JSON.stringify(payload) }),
  getYoutubeSlotSettings: () => request('/settings/youtube-slots'),
  getTeamPersonFilter: () => request('/settings/team-person-filter'),
  updateTeamPersonFilter: ({ team = '', selectedPeople = [] }) => request('/settings/team-person-filter', {
    method: 'PUT',
    body: JSON.stringify({ team, selected_people: selectedPeople }),
  }),
  getYoutubeDraftSettings: () => request('/settings/youtube-drafts'),
  updateYoutubeDraftSettings: (videoType, config) => request('/settings/youtube-drafts', { method: 'PUT', body: JSON.stringify({ video_type: videoType, config }) }),
  getWorkState: () => request('/settings/work-state'),
  updateWorkState: (key, value) => request('/settings/work-state', { method: 'PUT', body: JSON.stringify({ key, value }) }),
  getSpreadsheetMetadata: (spreadsheetUrlOrId) => request('/sheets/metadata', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId }) }),
  parseSheetOptions: (spreadsheetUrlOrId, worksheetName) => request('/sheets/parse-options', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName }) }),
  getTeamPeople: (spreadsheetUrlOrId, worksheetName, team) => request('/sheets/people', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName, team }) }),
  getRandomMemberPreview: (spreadsheetUrlOrId, worksheetName, team, columns) => request('/sheets/random-member-preview', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName, team, columns }) }),
  getCopyableSheetTable: (spreadsheetUrlOrId, worksheetName) => request('/sheets/copy-table', { method: 'POST', body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, worksheet_name: worksheetName }) }),
  getYoutubeQuotaUsage: (slot) => request(`/youtube/quota-usage${slot ? `?slot=${encodeURIComponent(slot)}` : ''}`),
  estimateYoutubeQuota: ({ operation, itemCount, slot }) => request('/youtube/quota-estimate', { method: 'POST', body: JSON.stringify({ operation, item_count: itemCount, ...(slot ? { slot } : {}) }) }),
  getPlaylistVideos: (playlistId) => request('/youtube/playlist-items', { method: 'POST', body: JSON.stringify({ playlist_id: playlistId }) }),
  updateYoutubeVideoMetadata: ({ videoId, title, description }) => request('/youtube/video-metadata', { method: 'POST', body: JSON.stringify({ video_id: videoId, title, description }) }),
  batchUpdateMetadata: ({ spreadsheetUrlOrId, videoType, worksheetName, titleColumn, descriptionColumn, team, assignments }) => request('/youtube/batch-update', { method: 'POST', timeoutMs: YOUTUBE_WORKFLOW_TIMEOUT_MS, body: JSON.stringify({ spreadsheet_url_or_id: spreadsheetUrlOrId, video_type: videoType, worksheet_name: worksheetName, title_column: titleColumn, description_column: descriptionColumn, team, assignments }) }),
  publishAndCleanup: (playlistId) => request('/youtube/publish-and-cleanup', { method: 'POST', timeoutMs: YOUTUBE_WORKFLOW_TIMEOUT_MS, body: JSON.stringify({ playlist_id: playlistId }) }),
};

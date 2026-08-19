export const PATHS = Object.freeze({
  root: '/',
  login: '/login',
  dashboard: '/dashboard',
  systemHealth: '/system/health',
  systemInfo: '/system/info',

  youtubeUploadNew: '/youtube/uploads/new',
  youtubeUploads: '/youtube/uploads',
  youtubeUploadJob: (jobId) => `/youtube/uploads/${encodeURIComponent(jobId)}`,
  youtubeVideoDrafts: '/youtube/drafts/videos',
  youtubeShortsDrafts: '/youtube/drafts/shorts',
  youtubePublishCleanup: '/youtube/publish-cleanup',

  youtubeSettings: '/youtube/settings',
  youtubeConnections: '/youtube/settings/connections',
  youtubeRouting: '/youtube/settings/routing',
  youtubeQuota: '/youtube/settings/quota',
  youtubePlaylist: '/youtube/settings/playlist',

  sheetCopy: '/sheets/copy',
  settings: '/settings',
  googleSettings: '/settings/google',
  sheetSettings: '/settings/sheets',
});

const RETURN_PATH_ALIASES = Object.freeze({
  [PATHS.youtubeSettings]: PATHS.youtubeConnections,
  [PATHS.settings]: PATHS.googleSettings,
  [PATHS.youtubeUploads]: PATHS.youtubeUploadNew,
});

const STATIC_RETURN_PATHS = new Set([
  PATHS.dashboard,
  PATHS.systemHealth,
  PATHS.systemInfo,
  PATHS.youtubeUploadNew,
  PATHS.youtubeVideoDrafts,
  PATHS.youtubeShortsDrafts,
  PATHS.youtubePublishCleanup,
  PATHS.youtubeConnections,
  PATHS.youtubeRouting,
  PATHS.youtubeQuota,
  PATHS.youtubePlaylist,
  PATHS.sheetCopy,
  PATHS.googleSettings,
  PATHS.sheetSettings,
  ...Object.keys(RETURN_PATH_ALIASES),
]);

export function isKnownProtectedPath(pathname) {
  if (STATIC_RETURN_PATHS.has(pathname)) return true;
  return /^\/youtube\/uploads\/[^/]+$/.test(pathname);
}

export function getCurrentPath(location = window.location) {
  return `${location.pathname}${location.search}`;
}

export function canonicalizeReturnPath(pathname) {
  return RETURN_PATH_ALIASES[pathname] || pathname;
}

/**
 * Validate a path before putting it in a login/OAuth return parameter.
 * Only known, protected, same-origin paths are accepted and hashes are never
 * carried across an authentication boundary.
 */
export function getSafeReturnPath(value) {
  if (typeof value !== 'string') return null;
  const candidate = value.trim();
  if (!candidate || candidate.includes('#') || candidate.startsWith('//')) return null;

  let url;
  try {
    url = new URL(candidate, window.location.origin);
  } catch {
    return null;
  }

  if (url.origin !== window.location.origin || !url.pathname.startsWith('/')) return null;
  if (url.pathname === PATHS.login || url.pathname.startsWith('/api/')) return null;
  const canonicalPathname = canonicalizeReturnPath(url.pathname);
  if (!isKnownProtectedPath(canonicalPathname)) return null;
  return `${canonicalPathname}${url.search}`;
}

export const isSafeReturnPath = (value) => Boolean(getSafeReturnPath(value));

export function buildLoginPath(returnTo) {
  const safePath = getSafeReturnPath(returnTo);
  return safePath ? `${PATHS.login}?returnTo=${encodeURIComponent(safePath)}` : PATHS.login;
}

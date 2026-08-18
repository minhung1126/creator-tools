import { getCurrentPath, getSafeReturnPath, PATHS } from '../routes/paths';

export const OAUTH_RETURN_KEYS = Object.freeze({
  google: 'creator-tools:oauth-return-to:google',
  youtube: 'creator-tools:oauth-return-to:youtube',
});

function keyFor(kind) {
  return OAUTH_RETURN_KEYS[kind] || OAUTH_RETURN_KEYS.google;
}

export function saveOAuthReturnPath(kind, path = getCurrentPath()) {
  const safePath = getSafeReturnPath(path);
  if (!safePath) return false;
  try {
    window.sessionStorage.setItem(keyFor(kind), safePath);
    return true;
  } catch {
    return false;
  }
}

export function consumeOAuthReturnPath(kind, fallback = PATHS.dashboard) {
  let stored = null;
  try {
    stored = window.sessionStorage.getItem(keyFor(kind));
    window.sessionStorage.removeItem(keyFor(kind));
  } catch {
    stored = null;
  }
  return getSafeReturnPath(stored) || fallback;
}


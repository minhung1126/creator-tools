const AUTH_HASH_KEYS = [
  ['instagram_auth_success', 'instagram_success'],
  ['instagram_auth_error', 'instagram_error'],
  ['auth_success', 'google_success'],
  ['auth_error', 'google_error'],
];

export function parseAuthHash(hash = window.location.hash) {
  const value = hash.startsWith('#') ? hash.slice(1) : hash;
  const params = new URLSearchParams(value);
  for (const [key, type] of AUTH_HASH_KEYS) {
    if (params.has(key)) {
      return { type, value: params.get(key) || '' };
    }
  }
  return null;
}

export function clearAuthHash() {
  window.history.replaceState(
    window.history.state,
    document.title,
    `${window.location.pathname}${window.location.search}`,
  );
}

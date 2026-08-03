export function readPersistentJson(key, fallback = {}) {
  try {
    if (typeof window === 'undefined') return fallback;
    const value = window.localStorage.getItem(key);
    if (!value) return fallback;
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function writePersistentJson(key, value) {
  try {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage can be unavailable or full. Server-side persistence remains
    // the source of truth for settings that are also sent to the API.
  }
}

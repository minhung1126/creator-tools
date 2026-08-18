import { beforeEach, describe, expect, it } from 'vitest';
import { consumeOAuthReturnPath, OAUTH_RETURN_KEYS, saveOAuthReturnPath } from './authReturnPath';

describe('OAuth return paths', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, '', '/youtube/uploads/new');
  });

  it('stores and consumes separate Google and YouTube return paths', () => {
    expect(saveOAuthReturnPath('google', '/youtube/uploads/new')).toBe(true);
    expect(saveOAuthReturnPath('youtube', '/youtube/settings/connections')).toBe(true);
    expect(window.sessionStorage.getItem(OAUTH_RETURN_KEYS.google)).toBe('/youtube/uploads/new');
    expect(consumeOAuthReturnPath('google', '/dashboard')).toBe('/youtube/uploads/new');
    expect(window.sessionStorage.getItem(OAUTH_RETURN_KEYS.google)).toBeNull();
    expect(consumeOAuthReturnPath('youtube', '/dashboard')).toBe('/youtube/settings/connections');
  });

  it('consumes unsafe values and uses a safe fallback', () => {
    window.sessionStorage.setItem(OAUTH_RETURN_KEYS.google, 'https://example.com/steal');
    expect(consumeOAuthReturnPath('google', '/dashboard')).toBe('/dashboard');
    expect(window.sessionStorage.getItem(OAUTH_RETURN_KEYS.google)).toBeNull();
  });
});


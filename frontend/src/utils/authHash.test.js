import { clearAuthHash, parseAuthHash } from './authHash';

describe('OAuth callback hash parsing', () => {
  it('uses exact Google callback keys', () => {
    expect(parseAuthHash('#auth_success=1')).toEqual({ type: 'google_success', value: '1' });
    expect(parseAuthHash('#auth_error=safe')).toEqual({ type: 'google_error', value: 'safe' });
    expect(parseAuthHash('#not_auth_success=1')).toBeNull();
  });

  it('clears the hash without navigating or replaying the callback', () => {
    window.history.replaceState({}, '', '/settings?tab=google#auth_success=1');
    clearAuthHash();
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=google');
    expect(window.location.hash).toBe('');
  });
});

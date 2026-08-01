import { clearAuthHash, parseAuthHash } from './authHash';

describe('OAuth callback hash parsing', () => {
  it('uses exact keys and Instagram precedence', () => {
    expect(parseAuthHash('#instagram_auth_success=1')).toEqual({ type: 'instagram_success', value: '1' });
    expect(parseAuthHash('#auth_success=1&instagram_auth_error=safe')).toEqual({ type: 'instagram_error', value: 'safe' });
    expect(parseAuthHash('#not_auth_success=1')).toBeNull();
  });

  it('clears the hash without navigating or replaying the callback', () => {
    window.history.replaceState({}, '', '/settings?tab=instagram#instagram_auth_success=1');
    clearAuthHash();
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=instagram');
    expect(window.location.hash).toBe('');
  });
});

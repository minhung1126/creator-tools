import { describe, expect, it, vi } from 'vitest';
import { buildPageRecoveryUrl, clearPageRecoveryParam, recoverPage } from './pageRecovery';

describe('page recovery', () => {
  it('preserves the current route while adding a one-time cache-busting parameter', () => {
    expect(buildPageRecoveryUrl('https://example.test/youtube/uploads/42?tab=log#details', 123)).toBe(
      'https://example.test/youtube/uploads/42?tab=log&__ct_resume=123#details',
    );
  });

  it('clears only the recovery parameter after the app mounts', () => {
    const replaceState = vi.fn();
    expect(clearPageRecoveryParam({
      href: 'https://example.test/dashboard?filter=active&__ct_resume=123#top',
      replaceState,
    })).toBe(true);
    expect(replaceState).toHaveBeenCalledWith('/dashboard?filter=active#top');
  });

  it('does not change a normal URL', () => {
    const replaceState = vi.fn();
    expect(clearPageRecoveryParam({ href: 'https://example.test/dashboard', replaceState })).toBe(false);
    expect(replaceState).not.toHaveBeenCalled();
  });

  it('navigates to the same page with a fresh recovery parameter', () => {
    const navigate = vi.fn();
    const target = recoverPage({ href: 'https://example.test/dashboard?filter=active', navigate, timestamp: 456 });
    expect(target).toBe('https://example.test/dashboard?filter=active&__ct_resume=456');
    expect(navigate).toHaveBeenCalledWith(target);
  });
});

import { beforeEach, describe, expect, it } from 'vitest';
import { resolveDraftConfig } from '../pages/BatchUpdatePage';
import { resolvePersistentValue, writePersistentJson } from './persistentStorage';

describe('persistent option recovery', () => {
  beforeEach(() => window.localStorage.clear());

  it('prefers an unsynchronized cached value over a server default', () => {
    const saved = { default_spreadsheet_id: 'cached-sheet', _pending: true };
    expect(resolvePersistentValue(saved, 'default_spreadsheet_id', '', '')).toBe('cached-sheet');
  });

  it('uses the server value after the cache is marked synchronized', () => {
    const saved = { quotaLimit: 5000, _pending: false };
    expect(resolvePersistentValue(saved, 'quotaLimit', 10000, 10000)).toBe(10000);
  });

  it('keeps storage writes available through the shared helper', () => {
    writePersistentJson('creator-tools.test', { value: 'ok' });
    expect(JSON.parse(window.localStorage.getItem('creator-tools.test'))).toEqual({ value: 'ok' });
  });

  it('does not let an empty server draft replace the cached draft', () => {
    const cached = { playlistId: 'cached-playlist' };
    expect(resolveDraftConfig({}, cached)).toBe(cached);
    expect(resolveDraftConfig({ playlistId: 'server-playlist' }, cached)).toEqual({ playlistId: 'server-playlist' });
  });
});

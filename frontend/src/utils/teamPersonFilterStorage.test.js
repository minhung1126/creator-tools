import { beforeEach, describe, expect, it } from 'vitest';
import {
  TEAM_PERSON_FILTER_STORAGE_KEY,
  normalizeTeamPersonFilter,
  readSharedTeamPersonFilter,
  stripTeamPersonFilter,
  writeSharedTeamPersonFilter,
} from './teamPersonFilterStorage';

describe('teamPersonFilterStorage', () => {
  beforeEach(() => window.localStorage.clear());

  it('normalizes aliases, whitespace and duplicate people', () => {
    expect(normalizeTeamPersonFilter({ selectedTeam: ' 團體 ', enabled_people: [' 甲 ', '甲', ''] })).toEqual({
      team: '團體',
      selectedPeople: ['甲'],
    });
  });

  it('prefers a pending local filter over the server value', () => {
    writeSharedTeamPersonFilter({ team: '本機團體', selectedPeople: ['甲'] }, { pending: true });

    expect(readSharedTeamPersonFilter({ configured: true, team: '伺服器團體', selected_people: ['乙'] })).toMatchObject({
      team: '本機團體',
      selectedPeople: ['甲'],
      pending: true,
    });
  });

  it('uses the server filter when there is no pending local update', () => {
    writeSharedTeamPersonFilter({ team: '舊本機團體', selectedPeople: ['甲'] });

    expect(readSharedTeamPersonFilter({ configured: true, team: '伺服器團體', selected_people: ['乙'] })).toMatchObject({
      team: '伺服器團體',
      selectedPeople: ['乙'],
      source: 'server',
    });
  });

  it('migrates the first available legacy filter and strips old fields from page caches', () => {
    window.localStorage.setItem('youtube-draft-config-video', JSON.stringify({ team: 'Video 團體', enabledPeople: ['甲'] }));
    expect(readSharedTeamPersonFilter()).toMatchObject({
      team: 'Video 團體',
      selectedPeople: ['甲'],
      source: 'legacy',
    });
    expect(stripTeamPersonFilter({ team: '團體', selectedPeople: ['甲'], playlistId: 'playlist' })).toEqual({ playlistId: 'playlist' });
  });

  it('writes one versioned shared record', () => {
    writeSharedTeamPersonFilter({ team: '團體', selectedPeople: ['甲'] });
    expect(JSON.parse(window.localStorage.getItem(TEAM_PERSON_FILTER_STORAGE_KEY))).toEqual({
      version: 1,
      team: '團體',
      selectedPeople: ['甲'],
      _pending: false,
    });
  });
});

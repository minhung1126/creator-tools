import { beforeEach, describe, expect, it } from 'vitest';
import {
  TEAM_PERSON_FILTER_STORAGE_KEY,
  normalizeTeamPersonFilter,
  readSharedTeamPersonFilter,
  writeSharedTeamPersonFilter,
} from './teamPersonFilterStorage';

describe('teamPersonFilterStorage', () => {
  beforeEach(() => window.localStorage.clear());

  it('normalizes the browser and server field names', () => {
    expect(normalizeTeamPersonFilter({ team: ' 團體 ', selected_people: [' 甲 ', '甲', ''] })).toEqual({
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

  it('uses the current local record when the server has no configured filter', () => {
    writeSharedTeamPersonFilter({ team: '本機團體', selectedPeople: ['甲'] });

    expect(readSharedTeamPersonFilter({ configured: false, team: '', selected_people: [] })).toMatchObject({
      team: '本機團體',
      selectedPeople: ['甲'],
      source: 'local',
    });
  });

  it('uses an empty default without a server or local record', () => {
    expect(readSharedTeamPersonFilter()).toEqual({
      team: '',
      selectedPeople: [],
      exists: false,
      pending: false,
      source: 'default',
    });
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

import { describe, expect, it } from 'vitest';
import {
  normalizeTeamPersonFilter,
  readSharedTeamPersonFilter,
} from './teamPersonFilterStorage';

describe('teamPersonFilterStorage', () => {
  it('normalizes the browser and server field names', () => {
    expect(normalizeTeamPersonFilter({ team: ' 團體 ', selected_people: [' 甲 ', '甲', ''] })).toEqual({
      team: '團體',
      selectedPeople: ['甲'],
    });
  });

  it('uses the server record when configured', () => {
    expect(readSharedTeamPersonFilter({ configured: true, team: '伺服器團體', selected_people: ['乙'] })).toMatchObject({
      team: '伺服器團體',
      selectedPeople: ['乙'],
      source: 'server',
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
});

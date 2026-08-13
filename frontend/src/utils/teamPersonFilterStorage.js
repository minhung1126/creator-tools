import { readPersistentJson, writePersistentJson } from './persistentStorage';

export const TEAM_PERSON_FILTER_STORAGE_KEY = 'creator-tools.team-person-filter.v1';

function normalizeText(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizePeople(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(normalizeText).filter(Boolean))];
}

export function normalizeTeamPersonFilter(value = {}) {
  const people = value?.selectedPeople ?? value?.selected_people;
  return {
    team: normalizeText(value?.team),
    selectedPeople: normalizePeople(people),
  };
}

export function readSharedTeamPersonFilter(serverFilter = null, { allowBrowserFallback = false } = {}) {
  const local = allowBrowserFallback ? readPersistentJson(TEAM_PERSON_FILTER_STORAGE_KEY, null) : null;
  if (local && typeof local === 'object' && local.version === 1 && local._pending === true) {
    return { ...normalizeTeamPersonFilter(local), exists: true, pending: true, source: 'local' };
  }

  if (serverFilter?.configured) {
    return { ...normalizeTeamPersonFilter(serverFilter), exists: true, pending: false, source: 'server' };
  }

  if (!allowBrowserFallback) {
    return { ...normalizeTeamPersonFilter(), exists: false, pending: false, source: 'default' };
  }

  if (local && typeof local === 'object' && local.version === 1) {
    return { ...normalizeTeamPersonFilter(local), exists: true, pending: false, source: 'local' };
  }

  return { ...normalizeTeamPersonFilter(), exists: false, pending: false, source: 'default' };
}

export function writeSharedTeamPersonFilter(value, { pending = false } = {}) {
  writePersistentJson(TEAM_PERSON_FILTER_STORAGE_KEY, {
    version: 1,
    ...normalizeTeamPersonFilter(value),
    _pending: pending,
  });
}

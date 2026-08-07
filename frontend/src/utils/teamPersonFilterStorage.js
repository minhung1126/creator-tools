import { readPersistentJson, writePersistentJson } from './persistentStorage';

export const TEAM_PERSON_FILTER_STORAGE_KEY = 'creator-tools.team-person-filter.v1';

const LEGACY_STORAGE_KEYS = [
  'youtube-draft-config-video',
  'youtube-draft-config-shorts',
  'creator-tools.sheet-copy.v1',
];

function normalizeText(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizePeople(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(normalizeText).filter(Boolean))];
}

export function normalizeTeamPersonFilter(value = {}) {
  const people = value?.selectedPeople ?? value?.selected_people ?? value?.enabledPeople ?? value?.enabled_people;
  return {
    team: normalizeText(value?.team ?? value?.selectedTeam),
    selectedPeople: normalizePeople(people),
  };
}

function hasFilterValue(filter) {
  return Boolean(filter.team || filter.selectedPeople.length);
}

function readLegacyFilter() {
  for (const key of LEGACY_STORAGE_KEYS) {
    const filter = normalizeTeamPersonFilter(readPersistentJson(key, {}));
    if (hasFilterValue(filter)) return filter;
  }
  return normalizeTeamPersonFilter();
}

export function readSharedTeamPersonFilter(serverFilter = null) {
  const local = readPersistentJson(TEAM_PERSON_FILTER_STORAGE_KEY, null);
  if (local && typeof local === 'object' && local.version === 1 && local._pending === true) {
    return { ...normalizeTeamPersonFilter(local), exists: true, pending: true, source: 'local' };
  }

  if (serverFilter?.configured) {
    return { ...normalizeTeamPersonFilter(serverFilter), exists: true, pending: false, source: 'server' };
  }

  if (local && typeof local === 'object' && local.version === 1) {
    return { ...normalizeTeamPersonFilter(local), exists: true, pending: false, source: 'local' };
  }

  const legacy = readLegacyFilter();
  return hasFilterValue(legacy)
    ? { ...legacy, exists: true, pending: false, source: 'legacy' }
    : { ...legacy, exists: false, pending: false, source: 'default' };
}

export function writeSharedTeamPersonFilter(value, { pending = false } = {}) {
  writePersistentJson(TEAM_PERSON_FILTER_STORAGE_KEY, {
    version: 1,
    ...normalizeTeamPersonFilter(value),
    _pending: pending,
  });
}

export function stripTeamPersonFilter(value = {}) {
  const next = { ...value };
  ['team', 'selectedTeam', 'selectedPeople', 'enabledPeople', 'enabled_people', 'person'].forEach((key) => {
    delete next[key];
  });
  return next;
}

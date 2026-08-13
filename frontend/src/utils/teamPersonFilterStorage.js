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

export function readSharedTeamPersonFilter(serverFilter = null) {
  if (serverFilter?.configured) {
    return { ...normalizeTeamPersonFilter(serverFilter), exists: true, pending: false, source: 'server' };
  }

  return { ...normalizeTeamPersonFilter(), exists: false, pending: false, source: 'default' };
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function keepAvailableOrder(values, available) {
  const wanted = new Set(asList(values));
  return asList(available).filter((value) => wanted.has(value));
}

export default function useTeamPersonFilter({
  source = '',
  worksheetName = '',
  enabled = true,
  initialTeam = '',
  initialSelectedPeople = [],
  defaultTeam = 'none',
  refreshKey = 0,
  apiClient = api,
}) {
  const initialSelectionRef = useRef({ team: initialTeam || '', people: asList(initialSelectedPeople) });
  const contextRef = useRef('');
  const hasLoadedContextRef = useRef(false);
  const teamRequestRef = useRef(0);
  const peopleRequestRef = useRef(0);
  const selectedTeamRef = useRef(initialTeam || '');
  const selectedPeopleRef = useRef(asList(initialSelectedPeople));
  const pendingPeopleRef = useRef(null);
  const defaultAllPeopleRef = useRef(false);

  const [teams, setTeams] = useState([]);
  const [selectedTeam, setSelectedTeamState] = useState(initialTeam || '');
  const [people, setPeople] = useState([]);
  const [selectedPeople, setSelectedPeopleState] = useState(asList(initialSelectedPeople));
  const [loadingTeams, setLoadingTeams] = useState(false);
  const [loadingPeople, setLoadingPeople] = useState(false);
  const [teamsReadyKey, setTeamsReadyKey] = useState('');
  const [error, setError] = useState('');
  const [errorType, setErrorType] = useState('');
  const contextKey = source && worksheetName ? `${source}\u0000${worksheetName}` : '';

  const setSelectedPeople = useCallback((nextPeople) => {
    const next = asList(nextPeople);
    pendingPeopleRef.current = null;
    defaultAllPeopleRef.current = false;
    selectedPeopleRef.current = next;
    setSelectedPeopleState(next);
  }, []);

  const selectTeam = useCallback((nextTeam, options = {}) => {
    const next = nextTeam || '';
    const previous = selectedTeamRef.current;
    const { preferredPeople } = options;
    const hasPreferredPeople = Object.prototype.hasOwnProperty.call(options, 'preferredPeople');
    if (previous !== next || hasPreferredPeople) {
      peopleRequestRef.current += 1;
      selectedTeamRef.current = next;
      setSelectedTeamState(next);
      setPeople([]);
      setLoadingPeople(false);
      const preferred = asList(preferredPeople);
      pendingPeopleRef.current = hasPreferredPeople && preferred.length ? preferred : null;
      defaultAllPeopleRef.current = next !== '' && (!hasPreferredPeople || preferred.length === 0);
      selectedPeopleRef.current = [];
      setSelectedPeopleState([]);
    } else {
      selectedTeamRef.current = next;
      setSelectedTeamState(next);
    }
  }, []);

  const resetSelection = useCallback(({ team = '', selectedPeople: nextPeople = [] } = {}) => {
    const normalizedPeople = asList(nextPeople);
    initialSelectionRef.current = { team: team || '', people: normalizedPeople };
    selectTeam(team, { preferredPeople: normalizedPeople });
  }, [selectTeam]);

  useEffect(() => {
    const requestId = teamRequestRef.current + 1;
    teamRequestRef.current = requestId;
    if (!enabled || !source || !worksheetName) {
      contextRef.current = '';
      setTeams([]);
      setPeople([]);
      setTeamsReadyKey('');
      setLoadingTeams(false);
      setLoadingPeople(false);
      setError('');
      setErrorType('');
      selectTeam('');
      return undefined;
    }

    const contextChanged = contextRef.current !== contextKey;
    const firstContextLoad = !hasLoadedContextRef.current;
    contextRef.current = contextKey;
    setTeamsReadyKey('');
    setLoadingTeams(true);
    setError('');
    setErrorType('');
    if (contextChanged) {
      const preference = firstContextLoad ? initialSelectionRef.current : { team: '', people: [] };
      selectTeam(preference.team, { preferredPeople: preference.people });
    }

    apiClient.parseSheetOptions(source, worksheetName)
      .then((result) => {
        if (teamRequestRef.current !== requestId) return;
        const nextTeams = asList(result?.teams);
        setTeams(nextTeams);
        const currentTeam = selectedTeamRef.current;
        const retainedTeam = nextTeams.includes(currentTeam) ? currentTeam : '';
        const nextTeam = retainedTeam || (defaultTeam === 'first' ? nextTeams[0] || '' : '');
        if (nextTeam !== currentTeam) selectTeam(nextTeam);
        else if (!nextTeam) selectTeam('');
        hasLoadedContextRef.current = true;
        setTeamsReadyKey(contextKey);
      })
      .catch((requestError) => {
        if (teamRequestRef.current !== requestId) return;
        setTeams([]);
        setPeople([]);
        setTeamsReadyKey('');
        selectTeam('');
        setError(`讀取團體失敗：${requestError.message}`);
        setErrorType('teams');
      })
      .finally(() => {
        if (teamRequestRef.current === requestId) setLoadingTeams(false);
      });
    return () => {
      if (teamRequestRef.current === requestId) teamRequestRef.current += 1;
    };
  }, [apiClient, contextKey, defaultTeam, enabled, refreshKey, selectTeam, source, worksheetName]);

  useEffect(() => {
    const requestId = peopleRequestRef.current + 1;
    peopleRequestRef.current = requestId;
    if (!enabled || !source || !worksheetName || !selectedTeam || teamsReadyKey !== contextKey) {
      setPeople([]);
      setLoadingPeople(false);
      if (!selectedTeam) {
        selectedPeopleRef.current = [];
        setSelectedPeopleState([]);
      }
      return undefined;
    }

    setLoadingPeople(true);
    setError('');
    setErrorType('');
    const requestedTeam = selectedTeam;
    const requestedContext = contextKey;
    apiClient.getTeamPeople(source, worksheetName, requestedTeam)
      .then((result) => {
        if (peopleRequestRef.current !== requestId || contextRef.current !== requestedContext || selectedTeamRef.current !== requestedTeam) return;
        const nextPeople = asList(result?.people);
        setPeople(nextPeople);
        let nextSelectedPeople;
        if (pendingPeopleRef.current) {
          nextSelectedPeople = keepAvailableOrder(pendingPeopleRef.current, nextPeople);
          pendingPeopleRef.current = null;
          defaultAllPeopleRef.current = false;
        } else if (defaultAllPeopleRef.current) {
          nextSelectedPeople = [...nextPeople];
          defaultAllPeopleRef.current = false;
        } else {
          nextSelectedPeople = keepAvailableOrder(selectedPeopleRef.current, nextPeople);
        }
        selectedPeopleRef.current = nextSelectedPeople;
        setSelectedPeopleState(nextSelectedPeople);
      })
      .catch((requestError) => {
        if (peopleRequestRef.current !== requestId || contextRef.current !== requestedContext || selectedTeamRef.current !== requestedTeam) return;
        setPeople([]);
        setSelectedPeopleState([]);
        selectedPeopleRef.current = [];
        setError(`讀取人物失敗：${requestError.message}`);
        setErrorType('people');
      })
      .finally(() => {
        if (peopleRequestRef.current === requestId) setLoadingPeople(false);
      });
    return () => {
      if (peopleRequestRef.current === requestId) peopleRequestRef.current += 1;
    };
  }, [apiClient, contextKey, enabled, refreshKey, selectedTeam, source, teamsReadyKey, worksheetName]);

  return {
    teams,
    selectedTeam,
    setSelectedTeam: selectTeam,
    people,
    selectedPeople,
    setSelectedPeople,
    loadingTeams,
    loadingPeople,
    loading: loadingTeams || loadingPeople,
    ready: Boolean(teamsReadyKey && teamsReadyKey === contextKey && !loadingTeams),
    error,
    errorType,
    resetSelection,
  };
}

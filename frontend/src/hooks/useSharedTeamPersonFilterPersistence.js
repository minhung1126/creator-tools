import { useEffect, useRef } from 'react';
import { api } from '../services/api';
import { normalizeTeamPersonFilter, writeSharedTeamPersonFilter } from '../utils/teamPersonFilterStorage';

export default function useSharedTeamPersonFilterPersistence({
  team = '',
  selectedPeople = [],
  ready = false,
  onError,
}) {
  const lastSavedRef = useRef('');
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!ready) return undefined;
    const filter = normalizeTeamPersonFilter({ team, selectedPeople });
    const serialized = JSON.stringify(filter);
    if (lastSavedRef.current === serialized) return undefined;

    lastSavedRef.current = serialized;
    writeSharedTeamPersonFilter(filter, { pending: true });
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const timer = window.setTimeout(() => {
      api.updateTeamPersonFilter(filter)
        .then((result) => {
          if (requestId !== requestIdRef.current) return;
          writeSharedTeamPersonFilter(result, { pending: false });
          onError?.('');
        })
        .catch((error) => {
          if (requestId !== requestIdRef.current) return;
          writeSharedTeamPersonFilter(filter, { pending: true });
          onError?.(`共用隊伍／人物篩選同步失敗：${error.message}`);
        });
    }, 500);

    return () => {
      window.clearTimeout(timer);
      requestIdRef.current += 1;
    };
  }, [onError, ready, selectedPeople, team]);
}

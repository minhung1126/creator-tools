import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';

const AccountWorkStateContext = createContext(null);

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function emptyStatus() {
  return {
    saving: false,
    saved: false,
    error: '',
    lastSaved: null,
  };
}

export function AccountWorkStateProvider({ initialState = {}, children }) {
  const [state, setState] = useState(() => asObject(initialState));
  const [statuses, setStatuses] = useState({});
  const recordsRef = useRef(new Map());
  const mountedRef = useRef(true);

  const updateStatus = useCallback((key, changes) => {
    if (!mountedRef.current) return;
    setStatuses((current) => ({
      ...current,
      [key]: { ...emptyStatus(), ...(current[key] || {}), ...changes },
    }));
  }, []);

  const getRecord = useCallback((key) => {
    let record = recordsRef.current.get(key);
    if (!record) {
      record = {
        timer: null,
        timerResolve: null,
        desiredValue: {},
        desiredVersion: 0,
        lastSavedVersion: 0,
        lastSavedValue: null,
        inFlightPromise: null,
      };
      recordsRef.current.set(key, record);
    }
    return record;
  }, []);

  const flushSave = useCallback((key) => {
    const record = recordsRef.current.get(key);
    if (!record) return Promise.resolve(null);
    if (record.inFlightPromise) return record.inFlightPromise;
    if (record.desiredVersion <= record.lastSavedVersion) {
      updateStatus(key, { saving: false, saved: true, error: '', lastSaved: record.lastSavedValue });
      return Promise.resolve(null);
    }

    const version = record.desiredVersion;
    const value = record.desiredValue;
    updateStatus(key, { saving: true, saved: false, error: '' });

    const request = Promise.resolve()
      .then(() => api.updateWorkState(key, value))
      .then((result) => {
        record.inFlightPromise = null;
        record.lastSavedVersion = version;
        record.lastSavedValue = value;

        if (mountedRef.current) {
          setState((current) => {
            const serverState = result?.state && typeof result.state === 'object' ? result.state : {};
            const next = { ...current, ...serverState };
            if (record.desiredVersion > version) next[key] = record.desiredValue;
            return next;
          });
        }

        const hasNewerValue = record.desiredVersion > version;
        if (hasNewerValue) {
          updateStatus(key, { saving: true, saved: false, error: '', lastSaved: value });
          if (!record.timer) return flushSave(key);
        } else {
          updateStatus(key, { saving: false, saved: true, error: '', lastSaved: value });
        }
        return result;
      })
      .catch((error) => {
        record.inFlightPromise = null;
        const hasNewerValue = record.desiredVersion > version;
        if (hasNewerValue) {
          updateStatus(key, { saving: true, saved: false, error: '' });
          if (!record.timer) return flushSave(key);
          return null;
        }

        updateStatus(key, {
          saving: false,
          saved: false,
          error: error?.message || '工作狀態同步失敗。',
        });
        return null;
      });

    record.inFlightPromise = request;
    return request;
  }, [updateStatus]);

  const scheduleSave = useCallback((key, debounceMs) => {
    const record = getRecord(key);
    if (record.timer) {
      window.clearTimeout(record.timer);
      record.timer = null;
      record.timerResolve?.(null);
      record.timerResolve = null;
    }

    if (debounceMs <= 0) return flushSave(key);

    return new Promise((resolve) => {
      record.timerResolve = resolve;
      record.timer = window.setTimeout(() => {
        record.timer = null;
        record.timerResolve = null;
        flushSave(key).then(resolve);
      }, debounceMs);
    });
  }, [flushSave, getRecord]);

  const save = useCallback((key, value, { debounceMs = 450 } = {}) => {
    const nextValue = asObject(value);
    const record = getRecord(key);
    record.desiredValue = nextValue;
    record.desiredVersion += 1;

    setState((current) => ({ ...current, [key]: nextValue }));
    updateStatus(key, { saving: true, saved: false, error: '' });
    return scheduleSave(key, debounceMs);
  }, [getRecord, scheduleSave, updateStatus]);

  const retry = useCallback((key) => {
    const record = recordsRef.current.get(key);
    if (!record || record.desiredValue === null || record.desiredValue === undefined) return Promise.resolve(null);
    record.desiredVersion += 1;
    updateStatus(key, { saving: true, saved: false, error: '' });
    return scheduleSave(key, 0);
  }, [scheduleSave, updateStatus]);

  useEffect(() => {
    mountedRef.current = true;
    const records = recordsRef.current;
    return () => {
      mountedRef.current = false;
      records.forEach((record) => {
        if (record.timer) window.clearTimeout(record.timer);
        record.timer = null;
        record.timerResolve?.(null);
        record.timerResolve = null;
      });
    };
  }, []);

  const contextValue = useMemo(() => ({
    ready: true,
    state,
    statuses,
    save,
    retry,
  }), [retry, save, state, statuses]);

  return createElement(AccountWorkStateContext.Provider, { value: contextValue }, children);
}

export default function useAccountWorkState(key, fallback = {}) {
  const context = useContext(AccountWorkStateContext);
  // The provider's context object changes whenever a stored value or status
  // changes, but its save/retry commands are stable. Depend on those commands
  // directly so consumers' autosave effects do not restart after every save.
  const contextSave = context?.save;
  const contextRetry = context?.retry;
  const save = useCallback(
    (value, options) => (contextSave ? contextSave(key, value, options) : Promise.resolve(null)),
    [contextSave, key],
  );
  const retry = useCallback(
    () => (contextRetry ? contextRetry(key) : Promise.resolve(null)),
    [contextRetry, key],
  );
  if (!context) {
    return {
      ready: false,
      value: fallback,
      saving: false,
      saved: false,
      error: '',
      lastSaved: null,
      retry,
      save,
    };
  }

  const status = context.statuses[key] || emptyStatus();
  return {
    ready: context.ready,
    value: context.state[key] === undefined ? fallback : context.state[key],
    saving: status.saving,
    saved: status.saved,
    error: status.error,
    lastSaved: status.lastSaved,
    retry,
    save,
  };
}

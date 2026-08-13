import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';

const AccountWorkStateContext = createContext(null);

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function AccountWorkStateProvider({ initialState = {}, children }) {
  const [state, setState] = useState(() => asObject(initialState));
  const [errors, setErrors] = useState({});
  const timersRef = useRef(new Map());
  const saveChainsRef = useRef(new Map());

  useEffect(() => () => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current.clear();
  }, []);

  const enqueueSave = useCallback((key, value) => {
    const previous = saveChainsRef.current.get(key) || Promise.resolve();
    const next = previous
      .catch(() => undefined)
      .then(async () => {
        try {
          const result = await api.updateWorkState(key, value);
          setErrors((current) => ({ ...current, [key]: '' }));
          if (result?.state && typeof result.state === 'object') {
            setState((current) => ({ ...current, ...result.state }));
          }
          return result;
        } catch (error) {
          setErrors((current) => ({ ...current, [key]: error.message || '工作狀態同步失敗。' }));
          return null;
        }
      });
    saveChainsRef.current.set(key, next);
    return next;
  }, []);

  const save = useCallback((key, value, { debounceMs = 450 } = {}) => {
    const nextValue = asObject(value);
    setState((current) => ({ ...current, [key]: nextValue }));
    setErrors((current) => ({ ...current, [key]: '' }));

    const previousTimer = timersRef.current.get(key);
    if (previousTimer) window.clearTimeout(previousTimer);
    if (debounceMs <= 0) return enqueueSave(key, nextValue);

    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        timersRef.current.delete(key);
        resolve(enqueueSave(key, nextValue));
      }, debounceMs);
      timersRef.current.set(key, timer);
    });
  }, [enqueueSave]);

  const contextValue = useMemo(() => ({
    ready: true,
    state,
    errors,
    save,
  }), [errors, save, state]);

  return createElement(AccountWorkStateContext.Provider, { value: contextValue }, children);
}

export default function useAccountWorkState(key, fallback = {}) {
  const context = useContext(AccountWorkStateContext);
  const save = useCallback(
    (value, options) => (context ? context.save(key, value, options) : Promise.resolve(null)),
    [context, key],
  );
  if (!context) {
    return {
      ready: false,
      value: fallback,
      saving: false,
      error: '',
      save,
    };
  }

  return {
    ready: context.ready,
    value: context.state[key] === undefined ? fallback : context.state[key],
    saving: false,
    error: context.errors[key] || '',
    save,
  };
}

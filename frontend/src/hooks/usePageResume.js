import { useCallback, useEffect, useRef, useState } from 'react';

export const PAGE_HIDDEN_RESUME_THRESHOLD_MS = 5 * 60 * 1000;
export const PAGE_RESUME_COOLDOWN_MS = 10 * 1000;

/**
 * Coordinate the browser events that indicate Safari may have suspended or
 * restored a page. The callback is intentionally invoked only on resume
 * signals; this hook never starts a background heartbeat.
 */
export function usePageResume(
  onResume,
  {
    hiddenThresholdMs = PAGE_HIDDEN_RESUME_THRESHOLD_MS,
    cooldownMs = PAGE_RESUME_COOLDOWN_MS,
  } = {},
) {
  const onResumeRef = useRef(onResume);
  const inactiveAtRef = useRef(null);
  const initialPageShowRef = useRef(true);
  const lastResumeAtRef = useRef(null);
  const resumePromiseRef = useRef(null);
  const mountedRef = useRef(true);
  const [isResuming, setIsResuming] = useState(false);

  useEffect(() => {
    onResumeRef.current = onResume;
  }, [onResume]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const requestResume = useCallback(({ force = false, reason = 'unknown' } = {}) => {
    if (resumePromiseRef.current) return resumePromiseRef.current;

    const now = Date.now();
    if (!force && lastResumeAtRef.current !== null && now - lastResumeAtRef.current < cooldownMs) {
      return Promise.resolve({ status: 'cooldown', reason });
    }

    lastResumeAtRef.current = now;
    if (mountedRef.current) setIsResuming(true);

    const promise = Promise.resolve()
      .then(() => onResumeRef.current?.({ reason }))
      .catch((error) => ({ status: 'error', error }))
      .finally(() => {
        if (resumePromiseRef.current === promise) resumePromiseRef.current = null;
        if (mountedRef.current) setIsResuming(false);
      });
    resumePromiseRef.current = promise;
    return promise;
  }, [cooldownMs]);

  useEffect(() => {
    const markInactive = () => {
      if (inactiveAtRef.current === null) inactiveAtRef.current = Date.now();
    };

    const resumeAfterInactivity = (reason) => {
      const inactiveAt = inactiveAtRef.current;
      inactiveAtRef.current = null;
      if (inactiveAt !== null && Date.now() - inactiveAt >= hiddenThresholdMs) {
        requestResume({ reason });
      }
    };

    if (document.hidden) markInactive();

    const handleVisibilityChange = () => {
      if (document.hidden) {
        markInactive();
        return;
      }
      resumeAfterInactivity('visibilitychange');
    };

    const handlePageShow = (event) => {
      if (event.persisted) {
        initialPageShowRef.current = false;
        inactiveAtRef.current = null;
        requestResume({ reason: 'pageshow-persisted' });
        return;
      }
      if (initialPageShowRef.current) {
        initialPageShowRef.current = false;
        return;
      }
      resumeAfterInactivity('pageshow');
    };

    const handlePageHide = () => {
      markInactive();
    };

    const handleBlur = () => {
      markInactive();
    };

    const handleFocus = () => {
      if (!document.hidden) resumeAfterInactivity('focus');
    };

    const handleOnline = () => {
      requestResume({ reason: 'online' });
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('pageshow', handlePageShow);
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener('blur', handleBlur);
    window.addEventListener('focus', handleFocus);
    window.addEventListener('online', handleOnline);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('pageshow', handlePageShow);
      window.removeEventListener('pagehide', handlePageHide);
      window.removeEventListener('blur', handleBlur);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('online', handleOnline);
    };
  }, [hiddenThresholdMs, requestResume]);

  const retryNow = useCallback(() => requestResume({ force: true, reason: 'manual' }), [requestResume]);

  return { isResuming, requestResume, retryNow };
}

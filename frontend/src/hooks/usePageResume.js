import { useCallback, useEffect, useRef, useState } from 'react';

export const PAGE_HIDDEN_RESUME_THRESHOLD_MS = 5 * 60 * 1000;
export const PAGE_RESUME_COOLDOWN_MS = 10 * 1000;
export const PAGE_REPAINT_OPACITY = '0.999999';

/**
 * Some browsers can restore a window with a stale compositor surface: the
 * DOM is still present, but only the page background is painted. Changing the
 * root opacity for one animation frame makes the browser rebuild that surface
 * without remounting React or disturbing the user's current form state.
 */
export function forcePageRepaint(root = typeof document !== 'undefined' ? document.getElementById('root') : null) {
  if (!root?.style) return () => {};

  const previousOpacity = root.style.opacity;
  let restored = false;
  root.style.opacity = PAGE_REPAINT_OPACITY;

  const restore = () => {
    if (restored) return;
    restored = true;
    root.style.opacity = previousOpacity;
  };

  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    const frame = window.requestAnimationFrame(restore);
    return () => {
      window.cancelAnimationFrame?.(frame);
      restore();
    };
  }

  if (typeof window !== 'undefined') {
    const timer = window.setTimeout(restore, 0);
    return () => {
      window.clearTimeout(timer);
      restore();
    };
  }

  restore();
  return () => {};
}

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
  const repaintCleanupRef = useRef(null);
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

  const repaintPage = useCallback(() => {
    repaintCleanupRef.current?.();
    repaintCleanupRef.current = forcePageRepaint();
  }, []);

  useEffect(() => () => {
    repaintCleanupRef.current?.();
    repaintCleanupRef.current = null;
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
      repaintPage();
      resumeAfterInactivity('visibilitychange');
    };

    const handlePageShow = (event) => {
      repaintPage();
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
      if (document.hidden) return;
      // Window focus does not always produce visibilitychange, especially on
      // desktop Safari. Repaint immediately even when the data refresh
      // threshold has not elapsed.
      repaintPage();
      resumeAfterInactivity('focus');
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
  }, [hiddenThresholdMs, repaintPage, requestResume]);

  const retryNow = useCallback(() => requestResume({ force: true, reason: 'manual' }), [requestResume]);

  return { isResuming, requestResume, retryNow };
}

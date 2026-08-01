import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';

const ActivityCenterContext = createContext(null);

const notificationToastType = {
  task_failed: 'error',
  task_paused: 'warning',
  task_warning: 'warning',
  canceled_with_warnings: 'warning',
  cancel_too_late: 'warning',
  credentials_unavailable: 'error',
  service_restart: 'warning',
};

export function ActivityCenterProvider({ children }) {
  const toast = useToast();
  const [summary, setSummary] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const seenNotificationKeys = useRef(null);
  const refreshInFlight = useRef(null);

  const refresh = useCallback(async ({ background = false } = {}) => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const promise = (async () => {
      if (!background) setRefreshing(true);
      const results = await Promise.allSettled([
        api.getActivitySummary(),
        api.getTasks({ offset: 0, limit: 100 }),
        api.getNotifications({ offset: 0, limit: 100 }),
      ]);
      const [summaryResult, tasksResult, notificationsResult] = results;
      let successCount = 0;
      if (summaryResult.status === 'fulfilled') {
        setSummary(summaryResult.value);
        successCount += 1;
      }
      if (tasksResult.status === 'fulfilled') {
        setTasks(tasksResult.value.items || tasksResult.value.tasks || []);
        successCount += 1;
      }
      if (notificationsResult.status === 'fulfilled') {
        const nextNotifications = notificationsResult.value.items || notificationsResult.value.notifications || [];
        setNotifications(nextNotifications);
        setUnreadCount(notificationsResult.value.unread_count ?? nextNotifications.filter((item) => !item.read_at).length);
        const nextKeys = new Set(nextNotifications.map((item) => item.event_key));
        if (seenNotificationKeys.current === null) {
          // Existing persisted notices are the initial snapshot, not live
          // arrivals.  Seed the set without showing a toast on first load.
          seenNotificationKeys.current = nextKeys;
        } else {
          nextNotifications
            .filter((item) => !seenNotificationKeys.current.has(item.event_key))
            .forEach((item) => {
              const type = notificationToastType[item.type] || (item.severity === 'error' ? 'error' : item.severity === 'warning' ? 'warning' : 'info');
              toast[type]?.(`${item.title}：${item.message}`);
            });
          nextKeys.forEach((key) => seenNotificationKeys.current.add(key));
        }
        successCount += 1;
      }
      if (successCount === 0) {
        setError('無法載入任務中心資料');
      } else {
        setError(null);
      }
      setLoading(false);
      setRefreshing(false);
    })().finally(() => {
      refreshInFlight.current = null;
    });
    refreshInFlight.current = promise;
    return promise;
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const activeCount = summary?.tasks?.active ?? tasks.filter((task) => ['queued', 'running', 'cancel_requested'].includes(task.status)).length;
  const hasAttention = Boolean((summary?.tasks?.paused || 0) + (summary?.tasks?.failed || 0));

  useEffect(() => {
    const onFocus = () => refresh({ background: true });
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refresh({ background: true });
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [refresh]);

  useEffect(() => {
    const intervalMs = activeCount > 0 ? 2000 : 20000;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') refresh({ background: true });
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [activeCount, refresh]);

  const runAndRefresh = useCallback(async (action) => {
    const result = await action();
    await refresh({ background: true });
    return result;
  }, [refresh]);

  const value = useMemo(() => ({
    summary,
    tasks,
    notifications,
    unreadCount,
    activeCount,
    hasAttention,
    loading,
    refreshing,
    error,
    refresh,
    cancelTask: (taskId) => runAndRefresh(() => api.cancelTask(taskId)),
    retryTask: (taskId) => runAndRefresh(() => api.retryTask(taskId)),
    cancelBatch: (batchId) => runAndRefresh(() => api.cancelTaskBatch(batchId)),
    retryBatch: (batchId) => runAndRefresh(() => api.retryTaskBatch(batchId)),
    stopInstagramBlockingJobs: (batchId) => runAndRefresh(() => api.stopInstagramBlockingJobs(batchId)),
    cancelAll: () => runAndRefresh(() => api.cancelAllTasks()),
    markNotificationRead: (notificationId) => runAndRefresh(() => api.markNotificationRead(notificationId)),
    markAllNotificationsRead: () => runAndRefresh(() => api.markAllNotificationsRead()),
    showToast: (type, message) => toast[type]?.(message),
  }), [activeCount, error, hasAttention, loading, notifications, refresh, refreshing, runAndRefresh, summary, tasks, toast, unreadCount]);

  return <ActivityCenterContext.Provider value={value}>{children}</ActivityCenterContext.Provider>;
}

export function useActivityCenterContext() {
  const context = useContext(ActivityCenterContext);
  if (!context) throw new Error('useActivityCenter must be used within ActivityCenterProvider');
  return context;
}

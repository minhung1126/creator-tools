export const YOUTUBE_ROUTING_MODES = {
  AUTO_PRIMARY: 'auto_primary',
  MANUAL: 'manual',
};

export function youtubeRoutingMode(youtube) {
  return youtube?.routing_mode === YOUTUBE_ROUTING_MODES.MANUAL
    ? YOUTUBE_ROUTING_MODES.MANUAL
    : YOUTUBE_ROUTING_MODES.AUTO_PRIMARY;
}

export function youtubePreferredUiSlot(youtube) {
  const slots = youtube?.slots || {};
  const activeSlot = youtube?.active_slot || 'primary';
  if (youtubeRoutingMode(youtube) === YOUTUBE_ROUTING_MODES.MANUAL) return activeSlot;
  if (slots.primary?.authenticated) return 'primary';
  if (slots.secondary?.authenticated) return 'secondary';
  return activeSlot;
}

export function youtubeIsConnected(youtube) {
  const slots = youtube?.slots || {};
  if (youtubeRoutingMode(youtube) === YOUTUBE_ROUTING_MODES.MANUAL) {
    return Boolean(slots[youtube?.active_slot || 'primary']?.authenticated);
  }
  return Object.values(slots).some((slot) => slot?.authenticated);
}

export function youtubeRoutingLabel(mode) {
  return mode === YOUTUBE_ROUTING_MODES.MANUAL ? '手動指定' : 'Auto：Primary 優先';
}

export function youtubeRoutingReasonLabel(reason) {
  const labels = {
    auto_primary_available: 'Primary 配額足夠，優先使用 Primary',
    auto_secondary_quota_fallback: 'Primary 執行途中配額不足，改用 Secondary 繼續',
    auto_secondary_quota_insufficient: 'Primary 本次配額不足，改用 Secondary',
    auto_secondary_youtube_quota_exhausted: 'Primary 配額已用完，改用 Secondary',
    auto_secondary_youtube_quota_safety_blocked: 'Primary 已達安全上限，改用 Secondary',
    auto_secondary_youtube_quota_storage_unavailable: 'Primary 配額記錄暫時不可用，改用 Secondary',
    auto_primary_quota_insufficient: 'Secondary 本次配額不足，改回 Primary',
    auto_primary_youtube_quota_exhausted: 'Secondary 配額已用完，改回 Primary',
    auto_primary_youtube_quota_safety_blocked: 'Secondary 已達安全上限，改回 Primary',
    auto_primary_youtube_quota_storage_unavailable: 'Secondary 配額記錄暫時不可用，改回 Primary',
    auto_primary_quota_fallback: 'Secondary 執行途中配額不足，改回 Primary 繼續',
    auto_secondary_not_connected: 'Primary 未連結，改用 Secondary',
    auto_secondary_not_configured: 'Primary 未配置，改用 Secondary',
    preview_pinned_slot: '沿用 preview 已選定的 slot',
    manual_active_slot: '手動使用目前作用中 slot',
  };
  return labels[reason] || reason || '尚未取得 routing 原因';
}

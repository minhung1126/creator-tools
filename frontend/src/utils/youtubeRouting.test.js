import { describe, expect, it } from 'vitest';
import {
  YOUTUBE_ROUTING_MODES,
  youtubeIsConnected,
  youtubePreferredUiSlot,
  youtubeRoutingLabel,
  youtubeRoutingMode,
  youtubeRoutingReasonLabel,
} from './youtubeRouting';

describe('YouTube routing helpers', () => {
  it('defaults unknown routing modes to auto-primary', () => {
    expect(youtubeRoutingMode()).toBe(YOUTUBE_ROUTING_MODES.AUTO_PRIMARY);
    expect(youtubeRoutingMode({ routing_mode: 'unsupported' })).toBe(YOUTUBE_ROUTING_MODES.AUTO_PRIMARY);
    expect(youtubeRoutingLabel('unsupported')).toBe('Auto：Primary 優先');
  });

  it('prefers an authenticated primary slot and falls back to secondary', () => {
    expect(youtubePreferredUiSlot({
      active_slot: 'secondary',
      slots: { primary: { authenticated: true }, secondary: { authenticated: true } },
    })).toBe('primary');
    expect(youtubePreferredUiSlot({
      active_slot: 'primary',
      slots: { primary: { authenticated: false }, secondary: { authenticated: true } },
    })).toBe('secondary');
    expect(youtubePreferredUiSlot({ active_slot: 'secondary', slots: {} })).toBe('secondary');
  });

  it('uses only the active slot for manual connectivity', () => {
    const manual = {
      routing_mode: 'manual',
      active_slot: 'primary',
      slots: { primary: { authenticated: false }, secondary: { authenticated: true } },
    };

    expect(youtubeIsConnected(manual)).toBe(false);
    expect(youtubeIsConnected({ ...manual, active_slot: 'secondary' })).toBe(true);
    expect(youtubeIsConnected({ ...manual, routing_mode: 'auto_primary' })).toBe(true);
  });

  it('provides safe routing explanations for known and unknown reasons', () => {
    expect(youtubeRoutingReasonLabel('preview_pinned_slot')).toBe('沿用 preview 已選定的 slot');
    expect(youtubeRoutingReasonLabel('new_reason')).toBe('new_reason');
    expect(youtubeRoutingReasonLabel('')).toBe('尚未取得 routing 原因');
  });
});

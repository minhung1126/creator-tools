import { describe, expect, it } from 'vitest';
import {
  formatCount,
  formatQuotaUnits,
  formatResultCounts,
  formatVideoCount,
  formatVideoId,
  formatVideoUploadTime,
  YOUTUBE_COPY,
} from './youtubeCopy';

describe('youtubeCopy', () => {
  it('keeps the shared action vocabulary in one place', () => {
    expect(YOUTUBE_COPY).toMatchObject({
      featureName: '發布草稿',
      setPublic: '設為公開',
      removeFromToPost: '移出 To-Post 播放清單',
      updateMetadata: '更新標題與描述',
      batchUpdate: '批次更新',
      readLoading: '讀取中…',
      updateLoading: '更新中…',
    });
  });

  it('formats counts, identifiers and quota units consistently', () => {
    expect(formatCount(1200)).toBe('1,200');
    expect(formatVideoCount(5)).toBe('5 支影片');
    expect(formatVideoId('abc123')).toBe('影片 ID：abc123');
    expect(formatQuotaUnits(100)).toBe('100 單位');
    expect(formatResultCounts({ succeeded_count: 1, skipped_count: 2, failed_count: 0, not_attempted_count: 3 }))
      .toBe('成功 1 支影片、略過 2 支影片、失敗 0 支影片、未執行 3 支影片');
  });

  it('keeps missing upload times explicit for stable ordering', () => {
    expect(formatVideoUploadTime()).toBe('未提供（排在最後）');
    expect(formatVideoUploadTime('2026-08-19T00:00:00.000Z')).toContain('2026');
  });
});

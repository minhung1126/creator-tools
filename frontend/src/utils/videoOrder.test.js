import { describe, expect, it } from 'vitest';
import { sortVideosByUploadTime } from './videoOrder';

describe('sortVideosByUploadTime', () => {
  it('puts dated videos first, uses sequence as the stable fallback, and preserves input', () => {
    const videos = [
      { video_id: 'unknown-late', sequence: 3 },
      { video_id: 'dated-late', published_at: '2026-01-02T00:00:00Z', sequence: 4 },
      { video_id: 'invalid-date', published_at: 'not-a-date', sequence: 2 },
      { video_id: 'dated-early', published_at: '2026-01-01T00:00:00Z', sequence: 1 },
    ];

    const sorted = sortVideosByUploadTime(videos);

    expect(sorted.map((video) => video.video_id)).toEqual([
      'dated-early',
      'dated-late',
      'invalid-date',
      'unknown-late',
    ]);
    expect(sorted).not.toBe(videos);
    expect(videos.map((video) => video.video_id)).toEqual([
      'unknown-late',
      'dated-late',
      'invalid-date',
      'dated-early',
    ]);
  });
});

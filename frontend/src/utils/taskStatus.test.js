import { describe, expect, it } from 'vitest';
import { isTaskRetryable, taskOperationLabel, taskStatusLabel } from './taskStatus';

describe('task status presentation', () => {
  it('distinguishes cancellation and warning states', () => {
    expect(taskStatusLabel('cancel_requested')).toBe('正在取消');
    expect(taskStatusLabel('canceled_with_warnings')).toBe('已取消但清理有警告');
    expect(isTaskRetryable({ status: 'succeeded_with_warnings', retryable: true })).toBe(true);
    expect(isTaskRetryable({ status: 'succeeded', retryable: true })).toBe(false);
  });

  it('labels the three supported operations', () => {
    expect(taskOperationLabel('instagram.reels_publish')).toContain('Instagram');
    expect(taskOperationLabel('youtube.metadata_update')).toContain('標題');
    expect(taskOperationLabel('youtube.publish_cleanup')).toContain('To-Post');
  });
});


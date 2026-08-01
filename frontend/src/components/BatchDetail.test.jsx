import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import BatchDetail from './BatchDetail';

describe('BatchDetail', () => {
  it('offers a safe stop action when old Instagram jobs block skipped videos', () => {
    const onStopBlocking = vi.fn();
    const batch = {
      id: 'batch-current',
      batch_short_code: 'BATCH_Y0',
      platform: 'instagram',
      status: 'completed',
      tasks: [
        {
          id: 'skipped-1',
          platform: 'instagram',
          operation: 'instagram.reels_publish',
          status: 'skipped',
          error: '此影片已有未完成的發布工作，請回到原工作重試。',
          progress_percent: 100,
        },
      ],
    };

    render(<BatchDetail batch={batch} onStopBlocking={onStopBlocking} />);
    fireEvent.click(screen.getByRole('button', { name: '強制停止占用中的舊工作' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('正在執行的任務會在下一個安全步驟停止');
    fireEvent.click(screen.getByRole('button', { name: '停止舊工作' }));
    expect(onStopBlocking).toHaveBeenCalledWith(batch);
  });
});

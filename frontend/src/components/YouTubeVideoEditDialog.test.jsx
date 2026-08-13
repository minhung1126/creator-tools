import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import YouTubeVideoEditDialog from './YouTubeVideoEditDialog';

const video = {
  video_id: 'abc123',
  title: '原本標題',
  description: '原本描述',
};

describe('YouTubeVideoEditDialog', () => {
  it('shows the current metadata and submits edited values', () => {
    const onSave = vi.fn();
    render(<YouTubeVideoEditDialog video={video} onSave={onSave} onClose={() => {}} />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('標題')).toHaveValue('原本標題');
    expect(screen.getByLabelText('描述')).toHaveValue('原本描述');
    expect(screen.getByRole('link', { name: /在 YouTube 查看影片/ })).toHaveAttribute(
      'href',
      'https://www.youtube.com/watch?v=abc123',
    );

    fireEvent.change(screen.getByLabelText('標題'), { target: { value: '更新後標題' } });
    fireEvent.change(screen.getByLabelText('描述'), { target: { value: '更新後描述' } });
    fireEvent.click(screen.getByRole('button', { name: '儲存變更' }));

    expect(onSave).toHaveBeenCalledWith({ title: '更新後標題', description: '更新後描述' });
  });

  it('does not submit a blank title', () => {
    const onSave = vi.fn();
    render(<YouTubeVideoEditDialog video={video} onSave={onSave} onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText('標題'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: '儲存變更' }));

    expect(onSave).not.toHaveBeenCalled();
  });
});

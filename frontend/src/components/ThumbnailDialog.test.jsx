import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import ThumbnailDialog from './ThumbnailDialog';

const image = { src: 'https://example.com/thumbnail.jpg', alt: '測試縮圖' };

describe('ThumbnailDialog', () => {
  it('zooms the large preview with the mouse wheel', () => {
    render(<ThumbnailDialog image={image} onClose={() => {}} />);

    const viewport = document.querySelector('.thumbnail-dialog-viewport');
    fireEvent.wheel(viewport, { deltaY: -100 });

    expect(screen.getByText('滾動滑鼠滾輪縮放 · 110%')).toBeInTheDocument();
    expect(screen.getByAltText('測試縮圖')).toHaveStyle({ transform: 'scale(1.1)' });
  });

  it('closes with Escape and resets zoom for a new image', () => {
    const onClose = vi.fn();
    const { rerender } = render(<ThumbnailDialog image={image} onClose={onClose} />);
    const viewport = document.querySelector('.thumbnail-dialog-viewport');

    fireEvent.wheel(viewport, { deltaY: -100 });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<ThumbnailDialog image={{ ...image, src: 'https://example.com/other.jpg' }} onClose={onClose} />);
    expect(screen.getByText('滾動滑鼠滾輪縮放 · 100%')).toBeInTheDocument();
  });
});

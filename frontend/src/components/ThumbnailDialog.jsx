import React, { useEffect } from 'react';
import { X } from 'lucide-react';

export default function ThumbnailDialog({ image, onClose }) {
  useEffect(() => {
    if (!image) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [image, onClose]);

  if (!image) return null;

  return (
    <div className="thumbnail-dialog-overlay" role="dialog" aria-modal="true" aria-label="影片縮圖放大預覽" onClick={onClose}>
      <div className="thumbnail-dialog-content" onClick={(event) => event.stopPropagation()}>
        <img className="thumbnail-dialog-image" src={image.src} alt={image.alt || '影片縮圖'} />
        <button type="button" className="thumbnail-dialog-close" aria-label="關閉縮圖預覽" onClick={onClose}><X size={22} /></button>
      </div>
    </div>
  );
}

import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;

export default function ThumbnailDialog({ image, onClose }) {
  const [zoom, setZoom] = useState(1);
  const [displaySrc, setDisplaySrc] = useState(image?.previewSrc || image?.src || '');

  useEffect(() => {
    if (!image) return undefined;
    setZoom(1);
    const previewSrc = image.previewSrc || image.src;
    setDisplaySrc(previewSrc);
    if (!image.src || image.src === previewSrc) return undefined;

    let cancelled = false;
    const highResolutionImage = new window.Image();
    highResolutionImage.onload = () => {
      if (!cancelled) setDisplaySrc(image.src);
    };
    highResolutionImage.src = image.src;
    return () => {
      cancelled = true;
      highResolutionImage.onload = null;
    };
  }, [image]);

  useEffect(() => {
    if (!image) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [image, onClose]);

  if (!image) return null;

  const handleWheel = (event) => {
    event.preventDefault();
    event.stopPropagation();
    const zoomFactor = event.deltaY < 0 ? 1.1 : 0.9;
    setZoom((currentZoom) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, currentZoom * zoomFactor)));
  };

  const handleImageError = () => {
    const fallbackSrc = image.previewSrc || image.fallbackSrc;
    if (fallbackSrc && displaySrc !== fallbackSrc) setDisplaySrc(fallbackSrc);
  };

  return (
    <div className="thumbnail-dialog-overlay" role="dialog" aria-modal="true" aria-label="影片縮圖放大預覽，可使用滑鼠滾輪縮放" onClick={onClose}>
      <div className="thumbnail-dialog-viewport" onClick={(event) => event.stopPropagation()} onWheel={handleWheel}>
        <img
          className="thumbnail-dialog-image"
          src={displaySrc}
          alt={image.alt || '影片縮圖'}
          onError={handleImageError}
          style={{ transform: `scale(${zoom})` }}
        />
      </div>
      <button type="button" className="thumbnail-dialog-close" aria-label="關閉縮圖預覽" onClick={onClose}><X size={22} /></button>
      <div className="thumbnail-dialog-hint" aria-live="polite">滾動滑鼠滾輪縮放 · {Math.round(zoom * 100)}%</div>
    </div>
  );
}

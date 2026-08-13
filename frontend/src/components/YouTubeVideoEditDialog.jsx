import React, { useEffect, useRef, useState } from 'react';
import { ExternalLink, Pencil, Save, X } from 'lucide-react';

const TITLE_MAX_LENGTH = 100;
const DESCRIPTION_MAX_LENGTH = 5000;

function youtubeVideoUrl(videoId) {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
}

export default function YouTubeVideoEditDialog({ video, saving = false, onSave, onClose }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const titleRef = useRef(null);
  const dialogRef = useRef(null);
  const savingRef = useRef(saving);

  useEffect(() => {
    savingRef.current = saving;
  }, [saving]);

  useEffect(() => {
    if (!video) return undefined;
    const previousActive = document.activeElement;
    setTitle(video.title || '');
    setDescription(video.description || '');
    titleRef.current?.focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (!savingRef.current) onClose?.();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled])')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previousActive instanceof HTMLElement) previousActive.focus();
    };
  }, [onClose, video]);

  if (!video) return null;

  const canSave = title.trim().length > 0 && title.length <= TITLE_MAX_LENGTH && description.length <= DESCRIPTION_MAX_LENGTH && !saving;
  const handleSubmit = (event) => {
    event.preventDefault();
    if (!canSave) return;
    onSave?.({ title: title.trim(), description });
  };
  const close = () => {
    if (!saving) onClose?.();
  };
  const videoUrl = youtubeVideoUrl(video.video_id);

  return (
    <div className="youtube-edit-overlay" role="presentation" onClick={close}>
      <div
        ref={dialogRef}
        className="youtube-edit-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="youtube-edit-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="youtube-edit-dialog-header">
          <div>
            <div className="youtube-edit-dialog-heading">
              <Pencil size={20} aria-hidden="true" />
              <h2 id="youtube-edit-dialog-title">編輯 YouTube 影片</h2>
            </div>
            <p className="youtube-edit-dialog-id">影片 ID：{video.video_id}</p>
          </div>
          <button type="button" className="youtube-edit-dialog-close" aria-label="關閉編輯視窗" onClick={close} disabled={saving}>
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <form className="youtube-edit-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <div className="youtube-edit-label-row">
              <label className="form-label" htmlFor="youtube-edit-title">標題</label>
              <span className="youtube-edit-counter">{title.length}/{TITLE_MAX_LENGTH}</span>
            </div>
            <input
              ref={titleRef}
              id="youtube-edit-title"
              className="form-input"
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={TITLE_MAX_LENGTH}
              required
            />
          </div>

          <div className="form-group">
            <div className="youtube-edit-label-row">
              <label className="form-label" htmlFor="youtube-edit-description">描述</label>
              <span className="youtube-edit-counter">{description.length}/{DESCRIPTION_MAX_LENGTH}</span>
            </div>
            <textarea
              id="youtube-edit-description"
              className="form-input youtube-edit-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={DESCRIPTION_MAX_LENGTH}
              rows={10}
            />
          </div>

          <a className="youtube-video-link youtube-edit-preview-link" href={videoUrl} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={15} aria-hidden="true" />
            編輯前後都可在 YouTube 查看影片
          </a>

          <div className="youtube-edit-dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={close} disabled={saving}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={!canSave}>
              <Save size={16} aria-hidden="true" />
              {saving ? '儲存中…' : '儲存變更'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

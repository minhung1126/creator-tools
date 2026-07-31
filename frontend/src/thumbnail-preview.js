function closeThumbnailPreview() {
  const overlay = document.querySelector('.thumbnail-preview-overlay');
  if (!overlay) return;

  overlay.remove();
  document.body.classList.remove('thumbnail-preview-open');
}

function openThumbnailPreview(sourceImage) {
  closeThumbnailPreview();

  const overlay = document.createElement('div');
  overlay.className = 'thumbnail-preview-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', '影片縮圖放大預覽');

  const content = document.createElement('div');
  content.className = 'thumbnail-preview-content';

  const image = document.createElement('img');
  image.className = 'thumbnail-preview-image';
  image.src = sourceImage.currentSrc || sourceImage.src;
  image.alt = sourceImage.alt || '影片縮圖';

  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'thumbnail-preview-close';
  closeButton.setAttribute('aria-label', '關閉縮圖預覽');
  closeButton.innerHTML = '&times;';
  closeButton.addEventListener('click', closeThumbnailPreview);

  content.append(image, closeButton);
  overlay.append(content);

  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) closeThumbnailPreview();
  });

  document.body.append(overlay);
  document.body.classList.add('thumbnail-preview-open');
  closeButton.focus();
}

function handleThumbnailClick(event) {
  const image = event.target.closest('.video-thumbnail');
  if (!image) return;

  event.preventDefault();
  openThumbnailPreview(image);
}

function handlePreviewKeydown(event) {
  if (event.key === 'Escape') closeThumbnailPreview();
}

document.addEventListener('click', handleThumbnailClick);
document.addEventListener('keydown', handlePreviewKeydown);

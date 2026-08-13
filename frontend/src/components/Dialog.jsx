import React, { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getFocusableElements(container) {
  return container
    ? [...container.querySelectorAll(FOCUSABLE_SELECTOR)].filter((element) => element.getAttribute('aria-hidden') !== 'true')
    : [];
}

export default function Dialog({
  open,
  children,
  titleId,
  descriptionId,
  label,
  initialFocusRef,
  onEscape,
  onBackdropClick,
  closeOnEscape = true,
  closeOnBackdrop = true,
  busy = false,
  className = '',
  overlayClassName = '',
}) {
  const dialogRef = useRef(null);
  const previousActiveRef = useRef(null);
  const onEscapeRef = useRef(onEscape);
  const onBackdropClickRef = useRef(onBackdropClick);
  const busyRef = useRef(busy);

  useEffect(() => {
    onEscapeRef.current = onEscape;
    onBackdropClickRef.current = onBackdropClick;
    busyRef.current = busy;
  }, [busy, onBackdropClick, onEscape]);

  useEffect(() => {
    if (!open) return undefined;

    previousActiveRef.current = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    const previousPaddingRight = document.body.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (scrollbarWidth > 0) document.body.style.paddingRight = `${scrollbarWidth}px`;

    const focusInitialElement = () => {
      const target = initialFocusRef?.current || getFocusableElements(dialogRef.current)[0] || dialogRef.current;
      target?.focus?.();
    };
    focusInitialElement();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        if (!closeOnEscape || busyRef.current) return;
        event.preventDefault();
        onEscapeRef.current?.();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;

      const focusable = getFocusableElements(dialogRef.current);
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      if (!dialogRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? focusable[focusable.length - 1] : focusable[0]).focus();
        return;
      }
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
      document.body.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousPaddingRight;
      const previousActive = previousActiveRef.current;
      if (previousActive && previousActive instanceof HTMLElement && document.body.contains(previousActive)) {
        previousActive.focus();
      }
    };
  }, [closeOnEscape, initialFocusRef, open]);

  if (!open) return null;

  const handleBackdropClick = () => {
    if (!closeOnBackdrop || busyRef.current) return;
    onBackdropClickRef.current?.();
  };

  return (
    <div
      className={`dialog-overlay ${overlayClassName}`.trim()}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleBackdropClick();
      }}
    >
      <div
        ref={dialogRef}
        className={`dialog-surface ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-busy={busy || undefined}
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-label={label}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

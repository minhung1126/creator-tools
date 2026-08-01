import React from 'react';
import { ExternalLink } from 'lucide-react';

const HTTP_PROTOCOL = /^https?:\/\//i;
const OTHER_PROTOCOL = /^[a-z][a-z\d+.-]*:/i;
const DOMAIN_NAME = /^(?:[a-z\d](?:[a-z\d-]*[a-z\d])?\.)+[a-z]{2,}(?::\d+)?(?:[/?#]|$)/i;

function normalizeHttpUrl(value) {
  const trimmed = String(value || '').trim();
  if (!trimmed || (OTHER_PROTOCOL.test(trimmed) && !HTTP_PROTOCOL.test(trimmed))) return '';

  const candidate = HTTP_PROTOCOL.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? candidate : '';
  } catch {
    return '';
  }
}

function looksLikeUrl(value) {
  return HTTP_PROTOCOL.test(value)
    || OTHER_PROTOCOL.test(value)
    || DOMAIN_NAME.test(value)
    || value.includes('/');
}

export function sourceUrlFromValue(value, sourceType = 'url') {
  const trimmed = String(value || '').trim();
  if (!trimmed) return '';

  if (sourceType === 'url' || looksLikeUrl(trimmed)) {
    return normalizeHttpUrl(trimmed);
  }

  const encodedValue = encodeURIComponent(trimmed);
  if (sourceType === 'spreadsheet') return `https://docs.google.com/spreadsheets/d/${encodedValue}/edit`;
  if (sourceType === 'drive-folder') return `https://drive.google.com/drive/folders/${encodedValue}`;
  if (sourceType === 'youtube-playlist') return `https://www.youtube.com/playlist?list=${encodedValue}`;
  return '';
}

export function SourceLinkButton({ value, sourceType = 'url', label = '開啟資料來源' }) {
  const href = sourceUrlFromValue(value, sourceType);
  const disabled = !href;

  return (
    <a
      className="source-link-button"
      href={href || undefined}
      target={href ? '_blank' : undefined}
      rel={href ? 'noopener noreferrer' : undefined}
      aria-label={label}
      aria-disabled={disabled}
      title={disabled ? '請先輸入來源網址或 ID' : label}
      tabIndex={disabled ? -1 : 0}
      onClick={(event) => { if (disabled) event.preventDefault(); }}
    >
      <ExternalLink size={17} aria-hidden="true" />
    </a>
  );
}

export default function SourceLinkInput({
  value,
  onChange,
  sourceType = 'url',
  linkLabel = '開啟資料來源',
  className = '',
  ...inputProps
}) {
  return (
    <div className="source-input-row">
      <input
        {...inputProps}
        className={`form-input ${className}`.trim()}
        value={value || ''}
        onChange={onChange}
      />
      <SourceLinkButton value={value} sourceType={sourceType} label={linkLabel} />
    </div>
  );
}

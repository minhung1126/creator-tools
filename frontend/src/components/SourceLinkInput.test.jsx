import React from 'react';
import { render, screen } from '@testing-library/react';
import SourceLinkInput, { sourceUrlFromValue } from './SourceLinkInput';

describe('SourceLinkInput', () => {
  it('converts provider IDs into editable source URLs', () => {
    expect(sourceUrlFromValue('sheet-123', 'spreadsheet')).toBe('https://docs.google.com/spreadsheets/d/sheet-123/edit');
    expect(sourceUrlFromValue('folder-456', 'drive-folder')).toBe('https://drive.google.com/drive/folders/folder-456');
    expect(sourceUrlFromValue('playlist-789', 'youtube-playlist')).toBe('https://www.youtube.com/playlist?list=playlist-789');
  });

  it('keeps a directly entered webpage and disables the icon when empty', () => {
    const { rerender } = render(<SourceLinkInput value="https://example.com/edit" onChange={() => {}} sourceType="spreadsheet" />);

    expect(screen.getByRole('link', { name: '開啟資料來源' })).toHaveAttribute('href', 'https://example.com/edit');

    rerender(<SourceLinkInput value="" onChange={() => {}} sourceType="spreadsheet" />);
    expect(document.querySelector('.source-link-button')).toHaveAttribute('aria-disabled', 'true');
  });

  it('opens scheme-less domains and rejects malformed URL-like values', () => {
    expect(sourceUrlFromValue('docs.example.com/edit', 'spreadsheet')).toBe('https://docs.example.com/edit');
    expect(sourceUrlFromValue(`javascript:${['alert', '(1)'].join('')}`, 'spreadsheet')).toBe('');
    expect(sourceUrlFromValue('https://', 'spreadsheet')).toBe('');
  });
});

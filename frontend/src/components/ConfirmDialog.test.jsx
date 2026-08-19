import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { vi } from 'vitest';
import ConfirmDialog from './ConfirmDialog';

describe('ConfirmDialog accessibility behavior', () => {
  it('traps focus, locks the background, restores focus, and prevents duplicate confirmation', async () => {
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.textContent = '開啟';
    document.body.appendChild(trigger);
    trigger.focus();

    let resolveConfirm;
    const onConfirm = vi.fn(() => new Promise((resolve) => { resolveConfirm = resolve; }));
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog
        open
        title="刪除項目"
        message="確定刪除嗎？"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const cancelButton = screen.getByRole('button', { name: '取消' });
    const confirmButton = screen.getByRole('button', { name: '確認' });
    expect(document.activeElement).toBe(cancelButton);
    expect(document.body.style.overflow).toBe('hidden');

    confirmButton.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(cancelButton);
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(confirmButton);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);

    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '處理中…' })).toBeDisabled();

    resolveConfirm();
    await waitFor(() => expect(screen.getByRole('button', { name: '確認' })).not.toBeDisabled());

    rerender(<ConfirmDialog open={false} onConfirm={onConfirm} onCancel={onCancel} />);
    expect(document.body.style.overflow).toBe('');
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it('renders structured content with a semantic list and keeps it as the dialog description', () => {
    render(
      <ConfirmDialog
        open
        title="確認發布 2 支影片"
        content={(
          <>
            <dl aria-label="發布摘要">
              <div><dt>影片數量</dt><dd>2 支影片</dd></div>
            </dl>
            <ol aria-label="實際確認影片">
              <li>影片一（影片 ID：video-1）</li>
              <li>影片二（影片 ID：video-2）</li>
            </ol>
          </>
        )}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '確認發布 2 支影片' });
    const description = document.getElementById('confirm-dialog-message');
    expect(description).toBeInTheDocument();
    expect(dialog).toHaveAttribute('aria-describedby', 'confirm-dialog-message');
    expect(within(description).getByRole('list', { name: '實際確認影片' })).toBeInTheDocument();
    expect(within(description).getAllByRole('listitem')).toHaveLength(2);
    expect(within(description).getAllByRole('listitem')[0]).toHaveTextContent('影片 ID：video-1');
  });
});

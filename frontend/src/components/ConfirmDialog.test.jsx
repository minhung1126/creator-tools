import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
});


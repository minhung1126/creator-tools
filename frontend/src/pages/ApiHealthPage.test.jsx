import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ApiHealthPage from './ApiHealthPage';

vi.mock('../components/YouTubeQuotaBanner', () => ({
  default: ({ refreshKey }) => <div data-testid="quota-refresh-key">{refreshKey}</div>,
}));

function setDocumentHidden(value) {
  Object.defineProperty(document, 'hidden', { configurable: true, value });
}

describe('ApiHealthPage visibility polling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setDocumentHidden(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    setDocumentHidden(false);
  });

  it('stops background polling and refreshes once when visible again', async () => {
    render(<ApiHealthPage authUser={{ youtube: {} }} />);
    expect(screen.getByTestId('quota-refresh-key')).toHaveTextContent('0');

    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(screen.getByTestId('quota-refresh-key')).toHaveTextContent('1');

    setDocumentHidden(true);
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    await act(async () => { vi.advanceTimersByTime(90000); });
    expect(screen.getByTestId('quota-refresh-key')).toHaveTextContent('1');

    setDocumentHidden(false);
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(screen.getByTestId('quota-refresh-key')).toHaveTextContent('2');

    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(screen.getByTestId('quota-refresh-key')).toHaveTextContent('3');
  });
});

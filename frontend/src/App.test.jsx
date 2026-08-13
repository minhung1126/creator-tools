import React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from './App';

function BrokenComponent() {
  throw new Error('private implementation details');
}

describe('ErrorBoundary', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows a safe recovery message without exposing the original JavaScript error', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('應用程式暫時無法顯示')).toBeInTheDocument();
    expect(screen.getByText('為保護錯誤內容，詳細資訊不會顯示。請重新載入頁面。')).toBeInTheDocument();
    expect(screen.queryByText('private implementation details')).not.toBeInTheDocument();
  });
});


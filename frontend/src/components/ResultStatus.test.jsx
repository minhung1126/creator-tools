import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ResultStatus from './ResultStatus';

describe('ResultStatus', () => {
  it('uses the five workflow result labels consistently', () => {
    render(
      <div>
        <ResultStatus status="succeeded" />
        <ResultStatus status="succeeded_with_warnings" />
        <ResultStatus status="skipped" />
        <ResultStatus status="failed" />
        <ResultStatus status="not_attempted" />
      </div>,
    );

    expect(screen.getByText('成功')).toBeInTheDocument();
    expect(screen.getByText('完成但需處理')).toBeInTheDocument();
    expect(screen.getByText('略過')).toBeInTheDocument();
    expect(screen.getByText('失敗')).toBeInTheDocument();
    expect(screen.getByText('未執行')).toBeInTheDocument();
  });
});


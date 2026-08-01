import React, { useEffect } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ToastProvider, useToast } from './Toast';

function OperationDemo() {
  const toast = useToast();

  useEffect(() => {
    toast.startOperation({
      id: 'instagram-job-1',
      title: 'Instagram Reels 發布',
      total: 40,
      completed: 0,
      percent: 2,
      message: '上傳到 Cloudflare R2 · 第 1 / 40 支',
    });
  }, [toast]);

  return null;
}

it('renders a persistent batch operation with stage and progress', async () => {
  render(<ToastProvider><OperationDemo /></ToastProvider>);

  await waitFor(() => expect(screen.getByText('上傳到 Cloudflare R2 · 第 1 / 40 支')).toBeInTheDocument());
  expect(screen.getByText('0 / 40 支完成')).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2');
});

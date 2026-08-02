import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ToastProvider, useToast } from './Toast';

function ToastDemo() {
  const toast = useToast();
  return <button type="button" onClick={() => toast.success('設定已儲存')}>顯示提示</button>;
}

it('renders an immediate toast message', () => {
  render(<ToastProvider><ToastDemo /></ToastProvider>);
  fireEvent.click(screen.getByRole('button', { name: '顯示提示' }));
  expect(screen.getByText('設定已儲存')).toBeInTheDocument();
});

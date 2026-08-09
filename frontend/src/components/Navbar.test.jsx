import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import Navbar from './Navbar';

function NavbarHarness() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  return <Navbar
    activeTab="dashboard"
    setActiveTab={() => {}}
    authUser={{ email: 'creator@example.com', youtube: { authenticated: false } }}
    onLogout={() => {}}
    sidebarCollapsed={sidebarCollapsed}
    setSidebarCollapsed={setSidebarCollapsed}
  />;
}

describe('Navbar', () => {
  it('keeps labels available until the user toggles the sidebar', () => {
    window.localStorage.clear();
    render(<NavbarHarness />);

    expect(screen.getByText('儀表板總覽')).toBeVisible();
    expect(screen.getByRole('button', { name: '收起側邊選單' })).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(screen.getByRole('button', { name: '收起側邊選單' }));

    expect(screen.getByText('儀表板總覽')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '展開側邊選單' })).toHaveAttribute('aria-expanded', 'false');
  });
});

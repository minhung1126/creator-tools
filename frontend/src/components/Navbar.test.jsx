import React, { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
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

  it('lists YouTube workflow pages in process order', () => {
    window.localStorage.clear();
    render(<NavbarHarness />);

    fireEvent.click(screen.getByRole('button', { name: 'YouTube' }));
    const submenu = document.getElementById('youtube-submenu');
    expect(within(submenu).getAllByRole('button').map((button) => button.textContent.trim())).toEqual([
      '上傳至 YouTube',
      'Video 草稿',
      'Shorts 草稿',
      '發布草稿並清理清單',
      'YouTube 設定',
    ]);
  });
});

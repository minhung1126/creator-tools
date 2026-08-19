import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { PATHS } from '../routes/paths';

const items = [
  [PATHS.youtubeConnections, '授權組合'],
  [PATHS.youtubeRouting, 'Routing'],
  [PATHS.youtubeQuota, 'Quota'],
  [PATHS.youtubePlaylist, '預設播放清單'],
];

export default function YouTubeSettingsLayout() {
  return (
    <div className="section-gap settings-page">
      <header className="page-header">
        <h1>YouTube 設定</h1>
        <p className="section-desc">管理 YouTube OAuth slot、頻道一致性、配額優先順序與發布預設資源。</p>
      </header>
      <nav className="settings-subnav" aria-label="YouTube 設定子導覽">
        {items.map(([to, label]) => <NavLink key={to} to={to} className={({ isActive }) => `settings-subnav-link${isActive ? ' active' : ''}`}>{label}</NavLink>)}
      </nav>
      <Outlet />
    </div>
  );
}

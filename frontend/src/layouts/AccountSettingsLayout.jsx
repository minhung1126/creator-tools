import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { PATHS } from '../routes/paths';

const items = [
  [PATHS.googleSettings, 'Google 帳號'],
  [PATHS.sheetSettings, '預設 Google Sheet'],
];

export default function AccountSettingsLayout() {
  return (
    <div className="section-gap settings-page">
      <header className="page-header">
        <h1>帳號與 Google 設定</h1>
        <p className="section-desc">管理控制台登入、Google Sheet 與部署資訊。</p>
      </header>
      <nav className="settings-subnav" aria-label="帳號設定子導覽">
        {items.map(([to, label]) => <NavLink key={to} to={to} className={({ isActive }) => `settings-subnav-link${isActive ? ' active' : ''}`}>{label}</NavLink>)}
      </nav>
      <Outlet />
    </div>
  );
}


import React, { useEffect, useRef, useState } from 'react';
import { Activity, CheckCircle2, ChevronDown, Clapperboard, Copy, FileSpreadsheet, LayoutDashboard, Menu, Send, Settings, Smartphone, Video, X, Youtube } from 'lucide-react';
import { readPersistentJson, writePersistentJson } from '../utils/persistentStorage';

const youtubeItems = [{ id: 'youtube_video_drafts', label: 'Video 草稿', icon: Clapperboard }, { id: 'youtube_shorts_drafts', label: 'Shorts 草稿', icon: Smartphone }, { id: 'publish_clean', label: '發布草稿並清理清單', icon: Send }, { id: 'youtube_settings', label: 'YouTube 設定', icon: Settings }];
const sheetItems = [{ id: 'sheet_copy', label: '內容複製', icon: Copy }];
const NAVIGATION_STORAGE_KEY = 'creator-tools.navigation.v1';

export default function Navbar({ activeTab, setActiveTab, authUser, onLogout }) {
  const savedNavigation = readPersistentJson(NAVIGATION_STORAGE_KEY, {});
  const [youtubeOpen, setYoutubeOpen] = useState(savedNavigation.youtubeOpen ?? youtubeItems.some((i) => i.id === activeTab));
  const [sheetOpen, setSheetOpen] = useState(savedNavigation.sheetOpen ?? sheetItems.some((i) => i.id === activeTab));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef(null);
  const closeButtonRef = useRef(null);
  const menuButtonRef = useRef(null);

  const closeDrawer = () => {
    setDrawerOpen(false);
    window.requestAnimationFrame(() => menuButtonRef.current?.focus());
  };

  useEffect(() => {
    if (youtubeItems.some((i) => i.id === activeTab)) setYoutubeOpen(true);
    if (sheetItems.some((i) => i.id === activeTab)) setSheetOpen(true);
    setDrawerOpen(false);
  }, [activeTab]);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDrawer();
        return;
      }
      if (event.key !== 'Tab' || !drawerRef.current) return;
      const focusable = [...drawerRef.current.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled])')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const onResize = () => {
      if (window.innerWidth >= 768) setDrawerOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', onResize);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', onResize);
    };
  }, [drawerOpen]);

  useEffect(() => {
    writePersistentJson(NAVIGATION_STORAGE_KEY, { ...readPersistentJson(NAVIGATION_STORAGE_KEY, {}), activeTab, youtubeOpen, sheetOpen });
  }, [activeTab, sheetOpen, youtubeOpen]);

  const item = (value, child = false) => {
    const Icon = value.icon;
    const active = activeTab === value.id;
    return <button key={value.id} type="button" className={`nav-item${child ? ' nav-item-child' : ''}${active ? ' active' : ''}`} onClick={() => setActiveTab(value.id)} title={value.label} aria-current={active ? 'page' : undefined}>
      <Icon size={child ? 16 : 18} aria-hidden="true" /><span>{value.label}</span>
    </button>;
  };

  const group = (id, label, Icon, open, setOpen, items) => {
    const groupActive = items.some((i) => i.id === activeTab);
    return <div className="nav-group">
      <button type="button" className={`nav-item nav-group-toggle${groupActive ? ' active' : ''}`} onClick={() => setOpen(!open)} title={label} aria-expanded={open} aria-controls={`${id}-submenu`}>
        <Icon size={18} aria-hidden="true" /><span>{label}</span><ChevronDown className="nav-group-chevron" size={16} aria-hidden="true" />
      </button>
      {open && <div id={`${id}-submenu`} className="nav-submenu">{items.map((i) => item(i, true))}</div>}
    </div>;
  };

  return <>
    <header className="mobile-app-bar">
      <div className="mobile-app-brand"><span className="brand-mark"><Video size={22} aria-hidden="true" /></span><strong>Creator Tools</strong></div>
      <button ref={menuButtonRef} type="button" className="app-bar-menu" onClick={() => setDrawerOpen(true)} aria-label="開啟導覽選單" aria-expanded={drawerOpen} aria-controls="primary-navigation">
        <Menu size={24} aria-hidden="true" />
      </button>
    </header>
    {drawerOpen && <button type="button" className="drawer-backdrop" aria-label="關閉導覽選單" onClick={closeDrawer} />}
    <aside ref={drawerRef} id="primary-navigation" className={`sidebar${drawerOpen ? ' is-open' : ''}`} aria-label="主要導覽">
      <div className="sidebar-brand"><div className="brand-mark"><Video size={24} aria-hidden="true" /></div><div className="sidebar-brand-copy"><h2>Creator Tools</h2><p>創作者自動化控制台</p></div><button ref={closeButtonRef} type="button" className="drawer-close" onClick={closeDrawer} aria-label="關閉導覽選單"><X size={22} aria-hidden="true" /></button></div>
      <nav className="sidebar-nav">
        {item({ id: 'dashboard', label: '儀表板總覽', icon: LayoutDashboard })}
        {item({ id: 'api_health', label: 'API健康度', icon: Activity })}
        {group('youtube', 'YouTube', Youtube, youtubeOpen, setYoutubeOpen, youtubeItems)}
        {group('sheet', 'Sheet', FileSpreadsheet, sheetOpen, setSheetOpen, sheetItems)}
        {item({ id: 'settings', label: '全域與 Google 設定', icon: Settings })}
      </nav>
      <div className="sidebar-footer"><div className="glass-panel account-card"><strong className="account-title">帳號資訊</strong><span className="badge badge-connected account-status"><CheckCircle2 size={12} />控制台已登入</span><p className="account-email">{authUser?.email}</p><span className={`badge account-youtube-status ${authUser?.youtube_authenticated ? 'badge-connected' : 'badge-disconnected'}`}>{authUser?.youtube_authenticated ? 'YouTube 已授權' : 'YouTube 未連結'}</span><button type="button" className="logout-button" onClick={onLogout}>登出控制台</button></div></div>
    </aside>
  </>;
}

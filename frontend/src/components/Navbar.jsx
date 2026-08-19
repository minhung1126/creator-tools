import React, { useEffect, useRef, useState } from 'react';
import { Activity, CheckCircle2, ChevronDown, Clapperboard, Copy, FileSpreadsheet, Info, LayoutDashboard, Menu, PanelLeftClose, PanelLeftOpen, Send, Settings, Smartphone, Upload, Video, X, Youtube } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import useAccountWorkState from '../hooks/useAccountWorkState';
import { youtubeIsConnected } from '../utils/youtubeRouting';
import { PATHS } from '../routes/paths';

const youtubeItems = [
  { id: 'youtube_upload', to: PATHS.youtubeUploadNew, label: '上傳至 YouTube', icon: Upload },
  { id: 'youtube_video_drafts', to: PATHS.youtubeVideoDrafts, label: 'Video 草稿', icon: Clapperboard },
  { id: 'youtube_shorts_drafts', to: PATHS.youtubeShortsDrafts, label: 'Shorts 草稿', icon: Smartphone },
  { id: 'publish_clean', to: PATHS.youtubePublishCleanup, label: '發布草稿', icon: Send },
  { id: 'youtube_settings', to: PATHS.youtubeConnections, label: 'YouTube 設定', icon: Settings, activePrefix: PATHS.youtubeSettings },
];
const sheetItems = [{ id: 'sheet_copy', to: PATHS.sheetCopy, label: '內容複製', icon: Copy }];

function pathIsActive(pathname, item) {
  if (item.activePrefix) return pathname === item.activePrefix || pathname.startsWith(`${item.activePrefix}/`);
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

export default function Navbar({ authUser, onLogout, sidebarCollapsed, setSidebarCollapsed }) {
  const location = useLocation();
  const pathname = location.pathname;
  const youtubeAuthorized = youtubeIsConnected(authUser?.youtube);
  const { value: savedNavigation, save: saveNavigation } = useAccountWorkState('navigation', {});
  const [youtubeOpen, setYoutubeOpen] = useState(savedNavigation.youtubeOpen ?? pathname.startsWith('/youtube/'));
  const [sheetOpen, setSheetOpen] = useState(savedNavigation.sheetOpen ?? pathname.startsWith('/sheets/'));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef(null);
  const closeButtonRef = useRef(null);
  const menuButtonRef = useRef(null);

  const closeDrawer = () => {
    setDrawerOpen(false);
    window.requestAnimationFrame?.(() => menuButtonRef.current?.focus());
  };

  useEffect(() => {
    if (pathname.startsWith('/youtube/')) setYoutubeOpen(true);
    if (pathname.startsWith('/sheets/')) setSheetOpen(true);
    setDrawerOpen(false);
  }, [pathname]);

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
    saveNavigation({ sidebarCollapsed, youtubeOpen, sheetOpen }, { debounceMs: 150 });
  }, [saveNavigation, sheetOpen, sidebarCollapsed, youtubeOpen]);

  const item = (value, child = false) => {
    const Icon = value.icon;
    return <NavLink
      key={value.id}
      to={value.to}
      end={!value.activePrefix}
      className={({ isActive }) => `nav-item${child ? ' nav-item-child' : ''}${(isActive || pathIsActive(pathname, value)) ? ' active' : ''}`}
      data-nav-id={value.id}
      onClick={closeDrawer}
      title={value.label}
      aria-current={pathIsActive(pathname, value) ? 'page' : undefined}
    >
      <Icon size={child ? 16 : 18} aria-hidden="true" /><span>{value.label}</span>
    </NavLink>;
  };

  const group = (id, label, Icon, open, setOpen, items, active) => (
    <div className="nav-group" key={id}>
      <button type="button" className={`nav-item nav-group-toggle${active ? ' active' : ''}`} data-nav-id={id} onClick={() => setOpen(!open)} title={label} aria-expanded={open} aria-controls={`${id}-submenu`} aria-current={active ? 'page' : undefined}>
        <Icon size={18} aria-hidden="true" /><span>{label}</span><ChevronDown className="nav-group-chevron" size={16} aria-hidden="true" />
      </button>
      {open && <div id={`${id}-submenu`} className="nav-submenu">{items.map((entry) => item(entry, true))}</div>}
    </div>
  );

  const youtubeActive = pathname.startsWith('/youtube/');
  const sheetActive = pathname.startsWith('/sheets/');
  const SidebarToggleIcon = sidebarCollapsed ? PanelLeftOpen : PanelLeftClose;
  const sidebarToggleLabel = sidebarCollapsed ? '展開側邊選單' : '收起側邊選單';

  return <>
    <header className="mobile-app-bar">
      <div className="mobile-app-brand"><span className="brand-mark"><Video size={22} aria-hidden="true" /></span><strong>Creator Tools</strong></div>
      <button ref={menuButtonRef} type="button" className="app-bar-menu" onClick={() => setDrawerOpen(true)} aria-label="開啟導覽選單" aria-expanded={drawerOpen} aria-controls="primary-navigation"><Menu size={24} aria-hidden="true" /></button>
    </header>
    {drawerOpen && <button type="button" className="drawer-backdrop" aria-label="關閉導覽選單" onClick={closeDrawer} />}
    <aside ref={drawerRef} id="primary-navigation" className={`sidebar${drawerOpen ? ' is-open' : ''}${sidebarCollapsed ? ' is-collapsed' : ''}`} aria-label="主要導覽">
      <div className="sidebar-brand"><div className="brand-mark"><Video size={24} aria-hidden="true" /></div><div className="sidebar-brand-copy"><h2>Creator Tools</h2><p>創作者自動化控制台</p></div><button type="button" className="sidebar-toggle" onClick={() => setSidebarCollapsed((collapsed) => !collapsed)} aria-label={sidebarToggleLabel} title={sidebarToggleLabel} aria-expanded={!sidebarCollapsed} aria-controls="primary-navigation"><SidebarToggleIcon size={20} aria-hidden="true" /></button><button ref={closeButtonRef} type="button" className="drawer-close" onClick={closeDrawer} aria-label="關閉導覽選單"><X size={22} aria-hidden="true" /></button></div>
      <nav className="sidebar-nav">
        {item({ id: 'dashboard', to: PATHS.dashboard, label: '儀表板總覽', icon: LayoutDashboard })}
        {item({ id: 'api_health', to: PATHS.systemHealth, label: 'API健康度', icon: Activity })}
        {item({ id: 'system_info', to: PATHS.systemInfo, label: '系統／部署資訊', icon: Info })}
        {group('youtube', 'YouTube', Youtube, youtubeOpen, setYoutubeOpen, youtubeItems, youtubeActive)}
        {group('sheet', 'Sheet', FileSpreadsheet, sheetOpen, setSheetOpen, sheetItems, sheetActive)}
        {item({ id: 'settings', to: PATHS.googleSettings, label: '帳號與 Google 設定', icon: Settings, activePrefix: '/settings' })}
      </nav>
      <div className="sidebar-footer"><div className="glass-panel account-card"><strong className="account-title">帳號資訊</strong><span className="badge badge-connected account-status"><CheckCircle2 size={12} />控制台已登入</span><p className="account-email">{authUser?.email}</p><span className={`badge account-youtube-status ${youtubeAuthorized ? 'badge-connected' : 'badge-disconnected'}`}>{youtubeAuthorized ? 'YouTube 已授權' : 'YouTube 未連結'}</span><button type="button" className="logout-button" onClick={onLogout}>登出控制台</button></div></div>
    </aside>
  </>;
}

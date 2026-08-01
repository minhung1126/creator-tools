import React, { useEffect, useState } from 'react';
import { Bell, CheckCircle2, ChevronDown, ChevronRight, Clapperboard, Copy, FileSpreadsheet, History, Instagram, LayoutDashboard, ListTodo, Loader2, Send, Settings, Smartphone, Video, Youtube } from 'lucide-react';
import { useActivityCenter } from '../hooks/useActivityCenter';

const youtubeItems = [{ id: 'youtube_video_drafts', label: 'Video 草稿', icon: Clapperboard }, { id: 'youtube_shorts_drafts', label: 'Shorts 草稿', icon: Smartphone }, { id: 'publish_clean', label: '發布草稿並清理清單', icon: Send }, { id: 'youtube_settings', label: 'YouTube 設定', icon: Settings }];
const sheetItems = [{ id: 'sheet_copy', label: '內容複製', icon: Copy }];
const instagramItems = [{ id: 'instagram_reels', label: 'Reels 自動發布', icon: Send }, { id: 'instagram_history', label: '發布歷史紀錄', icon: History }, { id: 'instagram_settings', label: 'Instagram / R2 設定', icon: Settings }];

export default function Navbar({ activeTab, setActiveTab, authUser, onLogout, onOpenNotifications }) {
  const { activeCount, unreadCount, hasAttention, tasks } = useActivityCenter();
  const [youtubeOpen, setYoutubeOpen] = useState(youtubeItems.some((i) => i.id === activeTab));
  const [sheetOpen, setSheetOpen] = useState(sheetItems.some((i) => i.id === activeTab));
  const [instagramOpen, setInstagramOpen] = useState(instagramItems.some((i) => i.id === activeTab));
  useEffect(() => {
    if (youtubeItems.some((i) => i.id === activeTab)) setYoutubeOpen(true);
    if (sheetItems.some((i) => i.id === activeTab)) setSheetOpen(true);
    if (instagramItems.some((i) => i.id === activeTab)) setInstagramOpen(true);
  }, [activeTab]);
  const item = (value, child = false) => { const Icon = value.icon; return <div key={value.id} className={`nav-item ${activeTab === value.id ? 'active' : ''}`} onClick={() => setActiveTab(value.id)} style={child ? { marginLeft: 22, padding: '10px 14px', fontSize: '.9rem' } : undefined}><Icon size={child ? 16 : 18} /><span>{value.label}</span></div>; };
  const group = (label, Icon, open, setOpen, items) => <div><button type="button" className={`nav-item ${items.some((i) => i.id === activeTab) ? 'active' : ''}`} onClick={() => setOpen(!open)} style={{ width: '100%', border: 0, font: 'inherit', textAlign: 'left' }}><Icon size={18} /><span style={{ flex: 1 }}>{label}</span>{open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button>{open && <div style={{ display: 'flex', flexDirection: 'column', gap: 4, margin: '4px 0 0 8px', paddingLeft: 8, borderLeft: '1px solid var(--border-color)' }}>{items.map((i) => item(i, true))}</div>}</div>;
  const taskNeedsAttention = !activeCount && tasks.some((task) => ['paused', 'failed'].includes(task.status));
  const taskCount = activeCount || (taskNeedsAttention ? tasks.filter((task) => ['paused', 'failed'].includes(task.status)).length : 0);
  const taskBadge = taskCount > 99 ? '99+' : taskCount;
  const notificationBadge = unreadCount > 99 ? '99+' : unreadCount;
  return <aside className="sidebar"><div><div style={{ display: 'flex', alignItems: 'center', gap: 12 }}><div style={{ background: 'linear-gradient(135deg,#6366f1,#ec4899)', padding: 8, borderRadius: 10 }}><Video size={24} /></div><div><h2 style={{ fontSize: '1.15rem' }}>Creator Tools</h2><p style={{ fontSize: '.75rem', color: 'var(--text-muted)' }}>創作者自動化控制台</p></div></div></div>
    <nav style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, overflowY: 'auto' }}>{item({ id: 'dashboard', label: '儀表板總覽', icon: LayoutDashboard })}{group('YouTube', Youtube, youtubeOpen, setYoutubeOpen, youtubeItems)}{group('Sheet', FileSpreadsheet, sheetOpen, setSheetOpen, sheetItems)}{group('Instagram', Instagram, instagramOpen, setInstagramOpen, instagramItems)}{item({ id: 'settings', label: '全域與 Google 設定', icon: Settings })}</nav>
    <div className="sidebar-utility" aria-label="活動入口">
      <button type="button" className={`sidebar-utility-item ${activeTab === 'task_queue' ? 'active' : ''}`} onClick={() => setActiveTab('task_queue')}><span className="sidebar-utility-icon">{tasks.some((task) => task.status === 'running') ? <Loader2 size={17} className="spin" /> : <ListTodo size={17} />}</span><span>任務隊列</span>{taskBadge > 0 && <span className={`sidebar-badge ${taskNeedsAttention || hasAttention && !activeCount ? 'warning' : ''}`}>{taskBadge}</span>}</button>
      <button type="button" className="sidebar-utility-item" onClick={onOpenNotifications}><span className="sidebar-utility-icon"><Bell size={17} /></span><span>通知中心</span>{unreadCount > 0 && <span className="sidebar-badge">{notificationBadge}</span>}</button>
    </div>
    <div className="sidebar-footer"><div className="glass-panel" style={{ padding: 14, fontSize: '.85rem' }}><strong style={{ color: '#fff' }}>帳號資訊</strong><span className="badge badge-connected" style={{ marginTop: 8 }}><CheckCircle2 size={12} />已連線</span><p style={{ marginTop: 8, wordBreak: 'break-all' }}>{authUser?.email}</p><button onClick={onLogout} style={{ marginTop: 8, color: '#f87171', background: 'none', border: 0 }}>登出</button></div></div>
  </aside>;
}

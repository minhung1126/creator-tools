import React, { useEffect, useState } from 'react';
import {
  LayoutDashboard,
  Settings,
  Send,
  Youtube,
  CheckCircle2,
  XCircle,
  Video,
  Clapperboard,
  Smartphone,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';

const youtubeItems = [
  { id: 'youtube_video_drafts', label: 'Video 草稿', icon: Clapperboard },
  { id: 'youtube_shorts_drafts', label: 'Shorts 草稿', icon: Smartphone },
  { id: 'publish_clean', label: '發布草稿並清理清單', icon: Send },
];

export default function Navbar({ activeTab, setActiveTab, authUser, onLogout }) {
  const isYoutubeTab = youtubeItems.some((item) => item.id === activeTab);
  const [isYoutubeOpen, setIsYoutubeOpen] = useState(isYoutubeTab);

  useEffect(() => {
    if (isYoutubeTab) setIsYoutubeOpen(true);
  }, [isYoutubeTab]);

  const renderNavItem = (item, isChild = false) => {
    const Icon = item.icon;
    const isActive = activeTab === item.id;
    return (
      <div
        key={item.id}
        className={`nav-item ${isActive ? 'active' : ''}`}
        onClick={() => setActiveTab(item.id)}
        style={isChild ? { marginLeft: '22px', padding: '10px 14px', fontSize: '0.9rem' } : undefined}
      >
        <Icon size={isChild ? 16 : 18} />
        <span>{item.label}</span>
      </div>
    );
  };

  return (
    <aside className="sidebar">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
          <div style={{ background: 'linear-gradient(135deg, #6366f1 0%, #ec4899 100%)', padding: '8px', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Video size={24} color="#ffffff" />
          </div>
          <div>
            <h2 style={{ fontSize: '1.15rem', color: '#fff' }}>Creator Tools</h2>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>創作者自動化控制台</p>
          </div>
        </div>
      </div>

      <nav style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 1 }}>
        {renderNavItem({ id: 'dashboard', label: '儀表板總覽', icon: LayoutDashboard })}
        <div>
          <button
            type="button"
            className={`nav-item ${isYoutubeTab ? 'active' : ''}`}
            onClick={() => setIsYoutubeOpen((open) => !open)}
            aria-expanded={isYoutubeOpen}
            aria-controls="youtube-nav-items"
            style={{ width: '100%', border: 'none', font: 'inherit', textAlign: 'left' }}
          >
            <Youtube size={18} />
            <span style={{ flex: 1 }}>YouTube</span>
            {isYoutubeOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>

          {isYoutubeOpen && (
            <div id="youtube-nav-items" style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px', marginLeft: '8px', paddingLeft: '8px', borderLeft: '1px solid var(--border-color)' }}>
              {youtubeItems.map((item) => renderNavItem(item, true))}
            </div>
          )}
        </div>
        {renderNavItem({ id: 'settings', label: '系統與帳號設定', icon: Settings })}
      </nav>

      <div className="glass-panel" style={{ padding: '14px', fontSize: '0.85rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>Google 連線狀態</span>
          {authUser ? <span className="badge badge-connected"><CheckCircle2 size={12} /> 已連線</span> : <span className="badge badge-disconnected"><XCircle size={12} /> 未連線</span>}
        </div>
        {authUser ? (
          <div>
            <p style={{ fontSize: '0.8rem', color: '#fff', wordBreak: 'break-all', fontWeight: 500 }}>{authUser.email || 'Google User'}</p>
            <button onClick={onLogout} style={{ marginTop: '8px', fontSize: '0.75rem', color: '#f87171', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>登出 / 切換帳號</button>
          </div>
        ) : <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>請至「系統設定」開啟認證連線</p>}
      </div>
    </aside>
  );
}

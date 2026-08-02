import React from 'react';
import {
  Clapperboard,
  Smartphone,
  Send,
  Settings,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Sparkles,
} from 'lucide-react';
import { SourceLinkButton } from '../components/SourceLinkInput';

export default function DashboardPage({ authUser, sysSettings, setActiveTab }) {
  return (
    <div className="section-gap">
      <div className="glass-panel" style={{ padding: '32px', background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(236, 72, 153, 0.1) 100%)' }}>
        <div className="badge badge-info" style={{ marginBottom: '12px' }}><Sparkles size={14} /> 創作者自動化工作流系統</div>
        <h1 style={{ fontSize: '2.2rem', marginBottom: '8px' }}>Creator Tools 控制台</h1>
        <p className="section-desc" style={{ maxWidth: '680px', lineHeight: 1.6 }}>Video 與 Shorts 草稿分開管理，可各自選擇工作表、標題欄位、描述欄位與人物選項。</p>
      </div>

      <div className="status-grid">
        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}><span style={{ color: 'var(--text-muted)' }}>Google API 連線</span>{authUser ? <span className="badge badge-connected"><CheckCircle2 size={12} /> 已授權</span> : <span className="badge badge-disconnected"><AlertTriangle size={12} /> 未授權</span>}</div>
          <h3 style={{ fontSize: '1rem', color: '#fff' }}>{authUser ? authUser.email : '尚未連線 Google 帳號'}</h3>
        </div>
        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}><span style={{ color: 'var(--text-muted)' }}>主要設定試算表</span><SourceLinkButton value={sysSettings.default_spreadsheet_id} sourceType="spreadsheet" label="開啟主要設定試算表" /></div>
          <h3 style={{ fontSize: '1rem', color: '#fff', wordBreak: 'break-all' }}>{sysSettings.default_spreadsheet_id || '未設定'}</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>頁面內再選擇要使用的工作表與欄位</p>
        </div>
        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}><span style={{ color: 'var(--text-muted)' }}>預設 To-Post 播放清單</span><SourceLinkButton value={sysSettings.default_playlist_id} sourceType="youtube-playlist" label="開啟預設 To-Post 播放清單" /></div>
          <h3 style={{ fontSize: '1rem', color: '#fff', wordBreak: 'break-all' }}>{sysSettings.default_playlist_id || '未設定'}</h3>
        </div>
      </div>

      <h2 style={{ fontSize: '1.4rem' }}>功能模組</h2>
      <div className="feature-grid">
        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-primary"><Clapperboard size={28} /></div>
          <div><h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>Video 草稿</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>使用 Video 專屬工作表、欄位與人物篩選設定。</p></div>
          <button className="btn btn-primary" onClick={() => setActiveTab('youtube_video_drafts')} style={{ marginTop: 'auto' }}>進入 Video 草稿 <ArrowRight size={16} /></button>
        </div>

        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-primary"><Smartphone size={28} /></div>
          <div><h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>Shorts 草稿</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>使用 Shorts 專屬工作表、欄位與人物篩選設定。</p></div>
          <button className="btn btn-primary" onClick={() => setActiveTab('youtube_shorts_drafts')} style={{ marginTop: 'auto' }}>進入 Shorts 草稿 <ArrowRight size={16} /></button>
        </div>

        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-secondary"><Send size={28} /></div>
          <div><h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>發布並清理清單</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>公開影片後自 To-Post 播放清單移除。</p></div>
          <button className="btn btn-primary" onClick={() => setActiveTab('publish_clean')} style={{ marginTop: 'auto' }}>進入發布模組 <ArrowRight size={16} /></button>
        </div>

        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-accent"><Settings size={28} /></div>
          <div><h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>全域與 Google 設定</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>管理登入授權、共用試算表與系統資訊；YouTube 設定位於 YouTube 分組中。</p></div>
          <button className="btn btn-secondary" onClick={() => setActiveTab('settings')} style={{ marginTop: 'auto' }}>進入系統設定 <ArrowRight size={16} /></button>
        </div>
      </div>
    </div>
  );
}

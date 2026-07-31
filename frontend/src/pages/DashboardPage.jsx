import React from 'react';
import {
  Layers,
  Send,
  Settings,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  PlaySquare,
  ArrowRight,
  Sparkles
} from 'lucide-react';

export default function DashboardPage({ authUser, sysSettings, setActiveTab }) {
  return (
    <div className="section-gap">
      {/* Header Banner */}
      <div className="glass-panel" style={{
        padding: '32px',
        background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(236, 72, 153, 0.1) 100%)',
        position: 'relative',
        overflow: 'hidden'
      }}>
        <div style={{ position: 'relative', zIndex: 2 }}>
          <div className="badge badge-info" style={{ marginBottom: '12px' }}>
            <Sparkles size={14} /> 創作者自動化工作流系統
          </div>
          <h1 style={{ fontSize: '2.2rem', marginBottom: '8px' }}>YouTube Creator Tools 控制台</h1>
          <p className="section-desc" style={{ maxWidth: '640px', lineHeight: 1.6 }}>
            整合 Google Sheets API 與 YouTube Data API，為創作者提供草稿影片標題說明批次更新、影片自動發布與播放清單清理等工作流。
          </p>
        </div>
      </div>

      {/* Quick Status Cards */}
      <div className="status-grid">
        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem', fontWeight: 500 }}>Google API 連線</span>
            {authUser ? (
              <span className="badge badge-connected"><CheckCircle2 size={12}/> 已授權</span>
            ) : (
              <span className="badge badge-disconnected"><AlertTriangle size={12}/> 未授權</span>
            )}
          </div>
          <h3 style={{ fontSize: '1.2rem', color: '#fff', marginBottom: '4px' }}>
            {authUser ? authUser.email : '尚未連線 Google 帳號'}
          </h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
            Scopes: Sheets (Read), YouTube (Full), Drive (Read)
          </p>
        </div>

        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem', fontWeight: 500 }}>預設對照試算表</span>
            <FileSpreadsheet size={18} color="var(--primary)" />
          </div>
          <h3 style={{ fontSize: '1rem', color: '#fff', marginBottom: '4px', wordBreak: 'break-all' }}>
            {sysSettings.default_spreadsheet_id || '未設定'}
          </h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
            含 Youtube Video 與 Youtube Shorts 工作表
          </p>
        </div>

        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem', fontWeight: 500 }}>預設 To-Post 播放清單</span>
            <PlaySquare size={18} color="var(--secondary)" />
          </div>
          <h3 style={{ fontSize: '1rem', color: '#fff', marginBottom: '4px', wordBreak: 'break-all' }}>
            {sysSettings.default_playlist_id || '未設定'}
          </h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
            草稿處理與公開清理目標清單
          </p>
        </div>
      </div>

      {/* Main Feature Cards */}
      <h2 style={{ fontSize: '1.4rem' }}>功能模組 Quick Entry</h2>

      <div className="feature-grid">
        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-primary">
            <Layers size={28} />
          </div>
          <div>
            <h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>批次更新草稿影片資訊</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.5 }}>
              依影片類型 (Video / Shorts) 與團體，讀取 Sheet 中已準備好的標題說明，一頁為每支草稿影片指定人物並批次覆寫 YouTube 標題與說明。
            </p>
          </div>
          <button className="btn btn-primary" onClick={() => setActiveTab('batch_update')} style={{ marginTop: 'auto' }}>
            進入批次更新模組 <ArrowRight size={16} />
          </button>
        </div>

        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-secondary">
            <Send size={28} />
          </div>
          <div>
            <h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>發布草稿影片並清理清單</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.5 }}>
              自動讀取 To-Post 播放清單項目，依發布時間由舊到新排序，將公開狀態切換為「公開」，成功後將其自 To-Post 播放清單移除。
            </p>
          </div>
          <button className="btn btn-primary" onClick={() => setActiveTab('publish_clean')} style={{ marginTop: 'auto', background: 'linear-gradient(135deg, #ec4899 0%, #be185d 100%)' }}>
            進入發布與清理模組 <ArrowRight size={16} />
          </button>
        </div>

        <div className="glass-panel glass-panel-interactive" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="icon-box icon-box-accent">
            <Settings size={28} />
          </div>
          <div>
            <h3 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>系統設定與資源管理</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.5 }}>
              統一管理 Google OAuth 認證、Google Sheets & Drive 預設網址/ID、以及預留未來的 Meta API 模組配置。
            </p>
          </div>
          <button className="btn btn-secondary" onClick={() => setActiveTab('settings')} style={{ marginTop: 'auto' }}>
            進入系統與帳號設定 <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

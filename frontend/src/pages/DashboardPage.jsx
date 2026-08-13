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
import { youtubePreferredUiSlot } from '../utils/youtubeRouting';

export default function DashboardPage({ authUser, sysSettings, setActiveTab }) {
  const activeSlot = youtubePreferredUiSlot(authUser?.youtube);
  const activeYoutube = authUser?.youtube?.slots?.[activeSlot] || {};

  return (
    <div className="section-gap">
      <header className="glass-panel dashboard-hero page-header">
        <div className="badge badge-info dashboard-eyebrow"><Sparkles size={14} /> 創作者自動化工作流系統</div>
        <h1>Creator Tools 控制台</h1>
        <p className="section-desc dashboard-hero-description">Video 與 Shorts 草稿分開管理，可各自選擇工作表、標題欄位與描述欄位；團體與人物篩選會在三個流程間共用。</p>
      </header>

      <div className="status-grid">
        <div className="glass-panel dashboard-status-card">
          <div className="dashboard-status-head"><span>控制台登入</span>{authUser ? <span className="badge badge-connected"><CheckCircle2 size={12} /> 已登入</span> : <span className="badge badge-disconnected"><AlertTriangle size={12} /> 未登入</span>}</div>
          <h3>{authUser ? authUser.email : '尚未登入控制台'}</h3>
        </div>
        <div className="glass-panel dashboard-status-card">
          <div className="dashboard-status-head"><span>YouTube 頻道授權</span>{activeYoutube.authenticated ? <span className="badge badge-connected"><CheckCircle2 size={12} /> 已授權</span> : <span className="badge badge-disconnected"><AlertTriangle size={12} /> 未連結</span>}</div>
          <h3>{activeYoutube.user?.email || '請在設定中連結品牌帳號'}</h3>
        </div>
        <div className="glass-panel dashboard-status-card">
          <div className="dashboard-status-head"><span>主要設定試算表</span><SourceLinkButton value={sysSettings.default_spreadsheet_id} sourceType="spreadsheet" label="開啟主要設定試算表" /></div>
          <h3>{sysSettings.default_spreadsheet_id || '未設定'}</h3>
          <p>頁面內再選擇要使用的工作表與欄位</p>
        </div>
        <div className="glass-panel dashboard-status-card">
          <div className="dashboard-status-head"><span>預設 To-Post 播放清單</span><SourceLinkButton value={sysSettings.default_playlist_id} sourceType="youtube-playlist" label="開啟預設 To-Post 播放清單" /></div>
          <h3>{sysSettings.default_playlist_id || '未設定'}</h3>
        </div>
      </div>

      <h2 className="section-title">功能模組</h2>
      <div className="feature-grid">
          <div className="glass-panel glass-panel-interactive feature-card">
          <div className="icon-box icon-box-primary"><Clapperboard size={28} /></div>
          <div className="feature-card-copy"><h3>Video 草稿</h3><p>使用 Video 專屬工作表與欄位，沿用共用團體與人物篩選。</p></div>
          <button className="btn btn-primary feature-card-action" onClick={() => setActiveTab('youtube_video_drafts')}>進入 Video 草稿 <ArrowRight size={16} /></button>
        </div>

        <div className="glass-panel glass-panel-interactive feature-card">
          <div className="icon-box icon-box-primary"><Smartphone size={28} /></div>
          <div className="feature-card-copy"><h3>Shorts 草稿</h3><p>使用 Shorts 專屬工作表與欄位，沿用共用團體與人物篩選。</p></div>
          <button className="btn btn-primary feature-card-action" onClick={() => setActiveTab('youtube_shorts_drafts')}>進入 Shorts 草稿 <ArrowRight size={16} /></button>
        </div>

        <div className="glass-panel glass-panel-interactive feature-card">
          <div className="icon-box icon-box-secondary"><Send size={28} /></div>
          <div className="feature-card-copy"><h3>發布並清理清單</h3><p>依序公開影片並自 To-Post 播放清單移除，完成後直接顯示結果。</p></div>
          <button className="btn btn-primary feature-card-action" onClick={() => setActiveTab('publish_clean')}>進入發布模組 <ArrowRight size={16} /></button>
        </div>

        <div className="glass-panel glass-panel-interactive feature-card">
          <div className="icon-box icon-box-accent"><Settings size={28} /></div>
          <div className="feature-card-copy"><h3>帳號與 Google 設定</h3><p>管理控制台登入與目前帳號的預設試算表；YouTube 頻道授權請至 YouTube 設定。</p></div>
          <button className="btn btn-secondary feature-card-action" onClick={() => setActiveTab('settings')}>進入系統設定 <ArrowRight size={16} /></button>
        </div>
      </div>
    </div>
  );
}

import React, { useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, Clapperboard, PlaySquare, Save, Smartphone, XCircle } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';

export default function YouTubeSettingsPage({ sysSettings, refreshSettings, setActiveTab }) {
  const toast = useToast();
  const [playlistId, setPlaylistId] = useState(sysSettings.default_playlist_id || '');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    setPlaylistId(sysSettings.default_playlist_id || '');
  }, [sysSettings.default_playlist_id]);

  const handleSave = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      await api.updateYoutubeSettings({ default_playlist_id: playlistId });
      await refreshSettings();
      setMsg({ type: 'success', text: 'YouTube 預設播放清單已儲存。' });
      toast.success('YouTube 設定已儲存');
    } catch (error) {
      setMsg({ type: 'error', text: error.message || '儲存失敗' });
      toast.error(`儲存失敗：${error.message || '未知錯誤'}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="section-gap" style={{ maxWidth: 1000 }}>
      <div>
        <h1 style={{ fontSize: '1.8rem', marginBottom: 6 }}>YouTube 設定</h1>
        <p className="section-desc">管理 YouTube 發布流程的預設資源；Google 帳號授權與共用 Sheet 請至「全域與 Google 設定」。</p>
      </div>

      {msg && <div className="info-banner">{msg.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}{msg.text}</div>}

      <form className="glass-panel card-padding" onSubmit={handleSave} style={{ display: 'grid', gap: 20 }}>
        <div>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '1.2rem' }}><PlaySquare size={20} color="var(--secondary)" /> YouTube 發布預設資源</h2>
          <p className="section-desc">這個播放清單是 YouTube 發布與清理流程的 fallback。Video／Shorts 草稿頁若保存了自己的播放清單，會優先使用工作流設定。</p>
        </div>
        <div className="form-group">
          <label className="form-label"><PlaySquare size={14} /> 預設 To-Post 播放清單 ID</label>
          <input className="form-input" value={playlistId} onChange={(event) => setPlaylistId(event.target.value)} placeholder="YouTube Playlist ID" />
        </div>
        <button className="btn btn-success" type="submit" disabled={saving} style={{ width: 'fit-content' }}><Save size={18} />{saving ? '儲存中...' : '儲存 YouTube 設定'}</button>
      </form>

      <section className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
        <div>
          <h2 style={{ fontSize: '1.2rem' }}>YouTube 草稿工作流設定</h2>
          <p className="section-desc">Video 與 Shorts 的工作表、欄位、團體、人物篩選與工作流資源，會在各自功能頁編輯並自動保存。</p>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 12 }}>
          <div className="glass-panel" style={{ padding: 16, display: 'grid', gap: 10 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1rem' }}><Clapperboard size={18} /> Video 草稿</h3>
            <p className="section-desc">管理 Video 專屬工作表、欄位與人物選項。</p>
            <button className="btn btn-secondary" type="button" onClick={() => setActiveTab('youtube_video_drafts')} style={{ width: 'fit-content' }}>前往 Video 設定 <ArrowRight size={16} /></button>
          </div>
          <div className="glass-panel" style={{ padding: 16, display: 'grid', gap: 10 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1rem' }}><Smartphone size={18} /> Shorts 草稿</h3>
            <p className="section-desc">管理 Shorts 專屬工作表、欄位與人物選項。</p>
            <button className="btn btn-secondary" type="button" onClick={() => setActiveTab('youtube_shorts_drafts')} style={{ width: 'fit-content' }}>前往 Shorts 設定 <ArrowRight size={16} /></button>
          </div>
        </div>
      </section>
    </div>
  );
}

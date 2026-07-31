import React, { useState } from 'react';
import { api } from '../services/api';
import { 
  Send, 
  PlaySquare, 
  RefreshCw, 
  CheckCircle2, 
  AlertTriangle, 
  Globe, 
  Trash2,
  ListOrdered
} from 'lucide-react';

export default function PublishCleanerPage({ sysSettings, authUser }) {
  const [playlistId, setPlaylistId] = useState(sysSettings.default_playlist_id || '');
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  // Read To-Post playlist items
  const handleLoadPlaylist = async () => {
    if (!authUser) {
      alert('請先在系統設定中連結 Google 帳號！');
      return;
    }
    setLoading(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      setVideos(res.videos || []);
    } catch (err) {
      setErrorMsg(`讀取 To-Post 播放清單失敗：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Run Publish & Cleanup
  const handlePublishAndClean = async () => {
    if (videos.length === 0) return;
    
    if (!confirm(`確定要將這 ${videos.length} 支影片設為「公開」並自 To-Post 播放清單移除嗎？\n（影片仍會保留在 YouTube 頻道中）`)) {
      return;
    }

    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.publishAndCleanup(playlistId);
      setResult(res);
      // Reload list after execution
      setVideos([]);
    } catch (err) {
      setErrorMsg(`發布與清理執行失敗：${err.message}`);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
          <Send size={24} color="var(--secondary)" />
          <h1 style={{ fontSize: '1.8rem' }}>YouTube｜公開 To-Post 影片並清理清單</h1>
        </div>
        <p style={{ color: 'var(--text-muted)' }}>
          讀取待發布 (To-Post) 播放清單中的全部影片，依發布時間由舊到新排序。確認後將公開狀態設為「公開」，成功後自動自清單移除。
        </p>
      </div>

      {/* Input Control Bar */}
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
        <div className="form-group" style={{ flex: 1, minWidth: '280px' }}>
          <label className="form-label"><PlaySquare size={14}/> To-Post 播放清單 ID</label>
          <input 
            className="form-input" 
            type="text" 
            value={playlistId}
            onChange={(e) => setPlaylistId(e.target.value)}
            placeholder="e.g. PLhu1MP3FpZmHar5qPZJkl6zCqXzddF4nC"
          />
        </div>
        <button 
          className="btn btn-primary"
          onClick={handleLoadPlaylist}
          disabled={loading}
          style={{ marginTop: 'auto', background: 'linear-gradient(135deg, #ec4899 0%, #be185d 100%)' }}
        >
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          {loading ? '讀取中...' : '讀取 To-Post 播放清單'}
        </button>
      </div>

      {/* Error Alert */}
      {errorMsg && (
        <div className="glass-panel" style={{ padding: '16px', borderLeft: '4px solid #ef4444', color: '#f87171', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <AlertTriangle size={20} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Video List & Summary View */}
      {videos.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div className="glass-panel" style={{ padding: '24px', borderLeft: '4px solid var(--secondary)' }}>
            <h2 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>
              確認公開並移除 {videos.length} 支影片
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.6 }}>
              按下「確認公開並移出 To-Post」後，系統會逐支將公開狀態設為<strong>「公開 (Public)」</strong>，並在成功後從 To-Post 播放清單移除。從播放清單移除不會刪除 YouTube 影片；影片仍會保留在 YouTube 頻道中。
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '1.1rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ListOrdered size={18}/> 待處理影片清單 (依發布時間由舊到新排列)：
            </h3>

            {videos.map((v, idx) => (
              <div 
                key={v.video_id} 
                className="glass-panel"
                style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}
              >
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--secondary)', minWidth: '40px' }}>
                  #{idx + 1}
                </span>

                {v.thumbnail_url && (
                  <img 
                    src={v.thumbnail_url} 
                    alt={v.title} 
                    style={{ width: '120px', aspectRatio: '16/9', borderRadius: 'var(--radius-sm)', objectFit: 'cover' }}
                  />
                )}

                <div style={{ flex: 1, minWidth: '220px' }}>
                  <h4 style={{ fontSize: '0.95rem', color: '#fff', marginBottom: '4px' }}>{v.title || '無標題影片'}</h4>
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>ID: {v.video_id}</span>
                  {v.published_at && (
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginLeft: '12px' }}>
                      發布時間: {new Date(v.published_at).toLocaleString()}
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="badge badge-info"><Globe size={12}/> 將設為公開</span>
                  <span className="badge badge-info" style={{ background: 'rgba(236, 72, 153, 0.15)', color: '#f472b6', borderColor: 'rgba(236, 72, 153, 0.3)' }}>
                    <Trash2 size={12}/> 移出清單
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Action Bar */}
          <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
              確認無誤後，請點擊右側按鈕啟動發布流程：
            </span>
            <button 
              className="btn btn-primary"
              style={{ padding: '12px 32px', fontSize: '1.05rem', background: 'linear-gradient(135deg, #ec4899 0%, #be185d 100%)' }}
              onClick={handlePublishAndClean}
              disabled={executing}
            >
              <Send size={18} /> {executing ? '逐支發布並清理中...' : '確認公開並移出 To-Post'}
            </button>
          </div>
        </div>
      )}

      {/* Completion Result Modal/Card */}
      {result && (
        <div className="glass-panel" style={{ padding: '24px', border: '1px solid rgba(236, 72, 153, 0.4)', background: 'rgba(15, 23, 42, 0.95)' }}>
          <h3 style={{ fontSize: '1.3rem', color: '#f472b6', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <CheckCircle2 size={22}/> To-Post 影片已公開並完成清理！
          </h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
            本次清單中的 {result.total_processed} 支影片已逐支設為公開，並從 To-Post 播放清單移除。影片仍保留在 YouTube 頻道中。
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {result.results.map((r, idx) => (
              <div 
                key={idx}
                style={{
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-md)',
                  background: 'rgba(236, 72, 153, 0.1)',
                  border: '1px solid rgba(236, 72, 153, 0.2)',
                  fontSize: '0.85rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}
              >
                <div>
                  <strong style={{ color: '#fff' }}>#{idx + 1} {r.title}</strong> (ID: {r.video_id})
                </div>
                <span className="badge badge-connected">公開並移出清單完成</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

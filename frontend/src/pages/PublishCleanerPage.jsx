import React, { useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import { useActivityCenter } from '../hooks/useActivityCenter';
import ConfirmDialog from '../components/ConfirmDialog';
import TaskDetail from '../components/TaskDetail';
import YouTubeQuotaBanner from '../components/YouTubeQuotaBanner';
import ThumbnailDialog from '../components/ThumbnailDialog';
import { sortVideosByUploadTime } from '../utils/videoOrder';
import SourceLinkInput from '../components/SourceLinkInput';
import {
  AlertTriangle,
  CheckCircle2,
  Globe,
  ListOrdered,
  PlaySquare,
  RefreshCw,
  Send,
  Trash2,
} from 'lucide-react';

export default function PublishCleanerPage({ sysSettings, authUser, setActiveTab }) {
  const toast = useToast();
  const { refresh, tasks, cancelTask, retryTask } = useActivityCenter();
  const [playlistId, setPlaylistId] = useState(sysSettings.default_playlist_id || '');
  const [videos, setVideos] = useState([]);
  const [playlistSource, setPlaylistSource] = useState('');
  const [playlistFallbackReason, setPlaylistFallbackReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [previewImage, setPreviewImage] = useState(null);
  const [quotaRefreshKey, setQuotaRefreshKey] = useState(0);
  const [quotaEstimate, setQuotaEstimate] = useState(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [taskBusyId, setTaskBusyId] = useState(null);

  const handleLoadPlaylist = async () => {
    if (!authUser) {
      toast.warning('請先在系統設定中連結 Google 帳號！');
      return;
    }
    setLoading(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      setVideos(sortVideosByUploadTime(res.videos || []));
      setPlaylistSource(res.source || '');
      setPlaylistFallbackReason(res.fallback_reason || '');
      setQuotaRefreshKey((key) => key + 1);
    } catch (err) {
      setErrorMsg(`讀取 To-Post 播放清單失敗：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const doPublish = async () => {
    setConfirmOpen(false);
    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const metadataByVideoId = Object.fromEntries(videos.map((video) => [video.video_id, video]));
      const res = await api.publishAndCleanup(playlistId);
      setResult({ ...res, metadataByVideoId });
      await refresh({ background: true });
      setVideos([]);
      setQuotaRefreshKey((key) => key + 1);
      toast.success(`已建立 ${res.total_count || res.task_ids?.length || 0} 支影片的公開與清理任務。`);
    } catch (err) {
      setErrorMsg(`發布與清理執行失敗：${err.message}`);
      toast.error('發布與清理執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const sourceLabel = playlistSource === 'youtube-api' ? 'YouTube API' : '';
  const resultTasks = result?.batch_id ? tasks.filter((task) => task.batch_id === result.batch_id) : [];
  const runTaskAction = async (action, taskId) => {
    setTaskBusyId(taskId);
    try {
      await action(taskId);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setTaskBusyId(null);
    }
  };

  const requestPublish = async () => {
    setEstimateLoading(true);
    try {
      setQuotaEstimate(await api.estimateYoutubeQuota({ operation: 'youtube.publish_cleanup', itemCount: videos.length }));
    } catch (error) {
      setQuotaEstimate(null);
      toast.warning(`無法取得 quota 預估，仍可建立任務：${error.message}`);
    } finally {
      setEstimateLoading(false);
    }
    setConfirmOpen(true);
  };

  const metadataBlock = (title, description) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: '3px' }}>標題</div>
        <div style={{ fontSize: '0.95rem', color: '#fff', fontWeight: 600 }}>{title || '無標題影片'}</div>
      </div>
      <div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: '3px' }}>描述</div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.55 }}>
          {description || '（無描述）'}
        </div>
      </div>
    </div>
  );

  return (
    <div className="section-gap">
      <ConfirmDialog
        open={confirmOpen}
        title="確認公開並清理清單"
        message={`確定要依上傳時間由最早到最晚，將這 ${videos.length} 支影片設為「公開」並自 To-Post 播放清單移除嗎？\n（影片仍會保留在 YouTube 頻道中）${quotaEstimate ? `\n最壞估算 ${Number(quotaEstimate.projected_units || 0).toLocaleString()} units；今天預計可處理 ${quotaEstimate.max_items_today ?? videos.length} 支，其餘 ${Math.max(videos.length - Number(quotaEstimate.max_items_today || 0), 0)} 支會自動跨日續跑。` : ''}`}
        confirmText={estimateLoading ? '估算中…' : '確認公開並移出 To-Post'}
        cancelText="取消"
        variant="destructive"
        onConfirm={doPublish}
        onCancel={() => setConfirmOpen(false)}
      />

      <YouTubeQuotaBanner refreshKey={quotaRefreshKey} />

      <div>
        <div className="section-header">
          <Send size={24} color="var(--secondary)" />
          <h1 style={{ fontSize: '1.8rem' }}>YouTube｜公開 To-Post 影片並清理清單</h1>
        </div>
        <p className="section-desc">
          讀取待發布影片後，依 YouTube 上傳時間由最早到最晚顯示與處理；執行時才呼叫必要的 YouTube API 完成公開與移出清單。
        </p>
      </div>

      <div className="glass-panel" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
        <div className="form-group" style={{ flex: 1, minWidth: '280px' }}>
          <label className="form-label"><PlaySquare size={14} /> To-Post 播放清單 ID</label>
          <SourceLinkInput type="text" value={playlistId} onChange={(e) => setPlaylistId(e.target.value)} sourceType="youtube-playlist" placeholder="YouTube Playlist ID" />
        </div>
        <button className="btn btn-primary" onClick={handleLoadPlaylist} disabled={loading} style={{ marginTop: 'auto', background: 'linear-gradient(135deg, #ec4899 0%, #be185d 100%)' }}>
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          {loading ? '讀取中...' : '讀取 To-Post 播放清單'}
        </button>
      </div>

      {sourceLabel && (
        <div className="info-banner">
          <ListOrdered size={15} color="var(--secondary)" />
          <span>
            播放清單來源：{sourceLabel}。顯示與實際處理都依上傳時間由最早到最晚；缺少上傳時間的影片排在最後並維持原始順序。
            {playlistFallbackReason ? ` 回退原因：${playlistFallbackReason}` : ''}
          </span>
        </div>
      )}

      {errorMsg && <div className="glass-panel error-alert"><AlertTriangle size={20} /><span>{errorMsg}</span></div>}

      {videos.length > 0 && (
        <div className="section-gap" style={{ gap: '20px' }}>
          <div className="glass-panel" style={{ padding: '24px', borderLeft: '4px solid var(--secondary)' }}>
            <h2 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>確認公開並移除 {videos.length} 支影片</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.6 }}>
              系統會依下方上傳時間順序逐支設為<strong>「公開（Public）」</strong>，成功後再從 To-Post 播放清單移除。移出播放清單不會刪除影片。
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '1.1rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ListOrdered size={18} /> 待處理影片清單（上傳時間：最早 → 最晚）：
            </h3>
            {videos.map((video, index) => (
              <div key={video.video_id} className="glass-panel" style={{ padding: '14px 18px', display: 'flex', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--secondary)', minWidth: '40px', paddingTop: '4px' }}>#{index + 1}</span>
                {video.thumbnail_url && <img className="publish-cleaner-thumbnail" src={video.thumbnail_url} alt={video.title} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.title })} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setPreviewImage({ src: video.thumbnail_url, alt: video.title }); }} role="button" tabIndex={0} />}
                <div style={{ flex: 1, minWidth: '260px' }}>
                  {metadataBlock(video.title, video.description)}
                  <div style={{ marginTop: '8px' }}>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>ID: {video.video_id}</span>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginLeft: '12px' }}>
                      上傳時間：{video.published_at ? new Date(video.published_at).toLocaleString() : '未提供（排在最後）'}
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingTop: '4px' }}>
                  <span className="badge badge-info"><Globe size={12} /> 將設為公開</span>
                  <span className="badge badge-info" style={{ background: 'rgba(236, 72, 153, 0.15)', color: '#f472b6', borderColor: 'rgba(236, 72, 153, 0.3)' }}><Trash2 size={12} /> 移出清單</span>
                </div>
              </div>
            ))}
          </div>

          <div className="glass-panel execution-bar">
            <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>確認上傳時間、標題與描述無誤後，啟動發布流程：</span>
            <button className="btn btn-primary" onClick={requestPublish} disabled={executing || estimateLoading} style={{ padding: '12px 32px', fontSize: '1.05rem', background: 'linear-gradient(135deg, #ec4899 0%, #be185d 100%)' }}>
              <Send size={18} /> {executing ? '逐支發布並清理中...' : '確認公開並移出 To-Post'}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="glass-panel" style={{ padding: '24px', border: '1px solid rgba(236, 72, 153, 0.4)', background: 'rgba(15, 23, 42, 0.95)' }}>
          <h3 style={{ fontSize: '1.3rem', color: '#f472b6', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}><CheckCircle2 size={22} /> 已建立公開與清理任務</h3>
          <p style={{ color: 'var(--text-muted)' }}>批次 ID：{result.batch_id} · 已建立 {result.total_count || result.task_ids?.length || 0} 支影片任務，其中 {result.skipped_count || 0} 支略過。</p>
          <button className="btn btn-secondary" type="button" style={{ marginTop: 12 }} onClick={() => setActiveTab?.('task_queue')}>到任務隊列查看</button>
          {resultTasks.map((task) => <TaskDetail key={task.id} task={task} compact busy={taskBusyId === task.id} onCancel={() => runTaskAction(cancelTask, task.id)} onRetry={() => runTaskAction(retryTask, task.id)} />)}
          {result.results && <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: 16 }}>
            {result.results.map((item, index) => (
              <div key={`${item.video_id}-${index}`} className="result-item" style={{ alignItems: 'flex-start', background: item.status === 'failed' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(236, 72, 153, 0.1)' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong style={{ color: '#fff' }}>#{index + 1}</strong>
                  <div style={{ marginTop: '6px' }}>{metadataBlock(item.title, item.description)}</div>
                  <div style={{ color: 'var(--text-dim)', fontSize: '0.78rem', marginTop: '8px' }}>ID: {item.video_id}</div>
                  {item.reason && <div style={{ color: '#f87171', fontSize: '0.8rem', marginTop: '4px' }}>原因：{item.reason}</div>}
                </div>
                <span className={`badge ${item.status === 'failed' ? 'badge-disconnected' : 'badge-connected'}`}>{item.status === 'failed' ? '失敗' : '公開並移出清單完成'}</span>
              </div>
            ))}
          </div>}
        </div>
      )}

      <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}

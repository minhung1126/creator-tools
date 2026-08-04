import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import ThumbnailDialog from '../components/ThumbnailDialog';
import { sortVideosByUploadTime } from '../utils/videoOrder';
import SourceLinkInput from '../components/SourceLinkInput';
import { readPersistentJson, writePersistentJson } from '../utils/persistentStorage';
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

const STORAGE_KEY = 'creator-tools.youtube-publish-cleaner.v1';

export default function PublishCleanerPage({ sysSettings, authUser }) {
  const toast = useToast();
  const saved = readPersistentJson(STORAGE_KEY, {});
  const [playlistId, setPlaylistId] = useState(saved.playlistId || sysSettings.default_playlist_id || '');
  const [videos, setVideos] = useState([]);
  const [playlistSource, setPlaylistSource] = useState('');
  const [playlistFallbackReason, setPlaylistFallbackReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [previewImage, setPreviewImage] = useState(null);
  const [quotaEstimate, setQuotaEstimate] = useState(null);
  const [estimateLoading, setEstimateLoading] = useState(false);

  useEffect(() => {
    writePersistentJson(STORAGE_KEY, { playlistId });
  }, [playlistId]);

  const handleLoadPlaylist = async () => {
    if (!authUser) {
      toast.warning('請先登入控制台！');
      return;
    }
    if (!authUser.youtube_authenticated && !authUser.youtube?.authenticated) {
      toast.warning('請先在「YouTube 設定」連結 YouTube 頻道 Google 帳號！');
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
      const res = await api.publishAndCleanup(playlistId);
      setResult(res);
      setVideos([]);
      const summary = `成功 ${res.succeeded_count || 0} 支、警告 ${res.warning_count || 0} 支、略過 ${res.skipped_count || 0} 支、失敗 ${res.failed_count || 0} 支`;
      if (res.quota_blocked || res.not_attempted_count) toast.warning(`公開與清理部分完成：${summary}`);
      else if (res.failed_count || res.warning_count) toast.warning(`公開與清理完成但有需注意項目：${summary}`);
      else toast.success(`公開與清理完成：${summary}`);
    } catch (err) {
      setErrorMsg(`發布與清理執行失敗：${err.message}`);
      toast.error('發布與清理執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const sourceLabel = playlistSource === 'youtube-api' ? 'YouTube API' : '';
  const requestPublish = async () => {
    setEstimateLoading(true);
    try {
      setQuotaEstimate(await api.estimateYoutubeQuota({ operation: 'youtube.publish_cleanup', itemCount: videos.length }));
    } catch (error) {
      setQuotaEstimate(null);
      toast.warning(`無法取得 quota 預估，仍可直接執行：${error.message}`);
    } finally {
      setEstimateLoading(false);
    }
    setConfirmOpen(true);
  };

  const metadataBlock = (title, description) => (
    <div className="metadata-block">
      <div>
        <div className="metadata-label">標題</div>
        <div className="metadata-title">{title || '無標題影片'}</div>
      </div>
      <div>
        <div className="metadata-label">描述</div>
        <div className="metadata-description">
          {description || '（無描述）'}
        </div>
      </div>
    </div>
  );

  return (
    <div className="section-gap publish-cleaner-page">
      <ConfirmDialog
        open={confirmOpen}
        title="確認公開並清理清單"
        message={`確定要依上傳時間由最早到最晚，直接將這 ${videos.length} 支影片設為「公開」並自 To-Post 播放清單移除嗎？\n（影片仍會保留在 YouTube 頻道中）${quotaEstimate ? `\n最壞估算 ${Number(quotaEstimate.projected_units || 0).toLocaleString()} units；目前配額預計可處理 ${quotaEstimate.max_items_today ?? videos.length} 支。若途中達上限，未執行項目需在官方重設後重新送出。` : ''}`}
        confirmText={estimateLoading ? '估算中…' : '確認公開並移出 To-Post'}
        cancelText="取消"
        variant="destructive"
        onConfirm={doPublish}
        onCancel={() => setConfirmOpen(false)}
      />

      <header className="page-header">
        <div className="section-header">
          <Send size={24} color="var(--secondary)" />
          <h1>YouTube｜公開 To-Post 影片並清理清單</h1>
        </div>
        <p className="section-desc">
          讀取待發布影片後，依 YouTube 上傳時間由最早到最晚顯示與處理；執行時才呼叫必要的 YouTube API 完成公開與移出清單。
        </p>
      </header>

      <div className="glass-panel card-padding toolbar publish-source-panel">
        <div className="form-group publish-source-field">
          <label className="form-label"><PlaySquare size={14} /> To-Post 播放清單 ID</label>
          <SourceLinkInput type="text" value={playlistId} onChange={(e) => setPlaylistId(e.target.value)} sourceType="youtube-playlist" placeholder="YouTube Playlist ID" />
        </div>
        <button className="btn btn-primary publish-action-button" onClick={handleLoadPlaylist} disabled={loading}>
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
        <div className="section-gap publish-workflow">
          <div className="glass-panel card-padding publish-summary-panel">
            <h2>確認公開並移除 {videos.length} 支影片</h2>
            <p>
              系統會依下方上傳時間順序逐支設為<strong>「公開（Public）」</strong>，成功後再從 To-Post 播放清單移除。移出播放清單不會刪除影片。
            </p>
          </div>

          <div className="publish-list">
            <h3 className="publish-list-heading">
              <ListOrdered size={18} /> 待處理影片清單（上傳時間：最早 → 最晚）：
            </h3>
            {videos.map((video, index) => (
              <div key={video.video_id} className="glass-panel publish-item">
                <span className="publish-item-index">#{index + 1}</span>
                {video.thumbnail_url && <img className="publish-cleaner-thumbnail" src={video.thumbnail_url} alt={video.title} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.title })} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setPreviewImage({ src: video.thumbnail_url, alt: video.title }); }} role="button" tabIndex={0} />}
                <div className="publish-item-content">
                  {metadataBlock(video.title, video.description)}
                  <div className="publish-item-meta">
                    <span>ID: {video.video_id}</span>
                    <span>
                      上傳時間：{video.published_at ? new Date(video.published_at).toLocaleString() : '未提供（排在最後）'}
                    </span>
                  </div>
                </div>
                <div className="publish-item-status">
                  <span className="badge badge-info"><Globe size={12} /> 將設為公開</span>
                  <span className="badge badge-info publish-remove-badge"><Trash2 size={12} /> 移出清單</span>
                </div>
              </div>
            ))}
          </div>

          <div className="glass-panel execution-bar">
            <span>確認上傳時間、標題與描述無誤後，啟動發布流程：</span>
            <button className="btn btn-primary publish-action-button" onClick={requestPublish} disabled={executing || estimateLoading}>
              <Send size={18} /> {executing ? '逐支發布並清理中...' : '確認公開並移出 To-Post'}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="glass-panel card-padding publish-result-panel card-stack">
          <h3 className={result.completed ? 'result-heading result-heading-publish-success' : 'result-heading result-heading-warning'}><CheckCircle2 size={22} /> {result.completed ? '公開與清理已執行完成' : '公開與清理部分完成'}</h3>
          <p className="section-desc">共 {result.total_count || 0} 支：成功 {result.succeeded_count || 0}、警告 {result.warning_count || 0}、略過 {result.skipped_count || 0}、失敗 {result.failed_count || 0}、未執行 {result.not_attempted_count || 0}。</p>
          {result.quota_blocked && <div className="info-banner"><AlertTriangle size={15} /><span>已達 YouTube 配額上限；未執行項目請於官方重設後重新讀取播放清單並送出。</span></div>}
          {result.results && <div className="publish-result-list">
            {result.results.map((item, index) => (
              <div key={`${item.video_id}-${index}`} className={`result-item result-row publish-result-item ${item.status === 'failed' ? 'publish-result-item-failed' : 'publish-result-item-success'}`}>
                <div>
                  <strong>#{index + 1}</strong>
                  <div className="publish-result-metadata">{metadataBlock(item.title, item.description)}</div>
                  <div className="result-meta">ID: {item.video_id}</div>
                  {item.reason && <div className={item.status === 'failed' ? 'result-reason result-reason-failed' : 'result-reason'}>說明：{item.reason}</div>}
                </div>
                <span className={`badge ${item.status === 'succeeded' ? 'badge-connected' : item.status === 'failed' ? 'badge-disconnected' : 'badge-warning'}`}>{item.status === 'succeeded' ? '完成' : item.status === 'succeeded_with_warnings' ? '完成但有警告' : item.status === 'failed' ? '失敗' : item.status === 'skipped' ? '略過' : '未執行'}</span>
              </div>
            ))}
          </div>}
        </div>
      )}

      <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}

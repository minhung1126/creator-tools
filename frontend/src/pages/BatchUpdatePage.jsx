import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import YouTubeQuotaBanner from '../components/YouTubeQuotaBanner';
import {
  AlertCircle,
  CheckCircle2,
  CheckSquare2,
  FileSpreadsheet,
  Filter,
  Info,
  Layers,
  ListFilter,
  PlaySquare,
  RefreshCw,
  Send,
  SlidersHorizontal,
  Users,
  Video as VideoIcon,
} from 'lucide-react';

export default function BatchUpdatePage({ sysSettings, authUser }) {
  const toast = useToast();
  const [spreadsheetId, setSpreadsheetId] = useState(sysSettings.default_spreadsheet_id || '');
  const [playlistId, setPlaylistId] = useState(sysSettings.default_playlist_id || '');
  const [videoType, setVideoType] = useState('Video');
  const [selectedTeam, setSelectedTeam] = useState('');
  const [teams, setTeams] = useState([]);
  const [teamPeople, setTeamPeople] = useState([]);
  const [peopleFilter, setPeopleFilter] = useState('');
  const [videos, setVideos] = useState([]);
  const [selectedVideoIds, setSelectedVideoIds] = useState([]);
  const [assignments, setAssignments] = useState({});
  const [playlistSource, setPlaylistSource] = useState('');
  const [playlistFallbackReason, setPlaylistFallbackReason] = useState('');
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [loadingVideos, setLoadingVideos] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [quotaRefreshKey, setQuotaRefreshKey] = useState(0);

  useEffect(() => {
    if (sysSettings.default_spreadsheet_id && !spreadsheetId) setSpreadsheetId(sysSettings.default_spreadsheet_id);
    if (sysSettings.default_playlist_id && !playlistId) setPlaylistId(sysSettings.default_playlist_id);
  }, [sysSettings]);

  useEffect(() => {
    if (!selectedTeam || !authUser) return;
    api.getTeamPeople(spreadsheetId, videoType, selectedTeam)
      .then((res) => setTeamPeople(res.people || []))
      .catch((err) => console.error('Error fetching people:', err));
  }, [selectedTeam, videoType, spreadsheetId, authUser]);

  const selectedVideos = useMemo(
    () => videos.filter((video) => selectedVideoIds.includes(video.video_id)),
    [videos, selectedVideoIds],
  );

  const visiblePeople = useMemo(
    () => teamPeople.filter((person) => !peopleFilter || person.toLowerCase().includes(peopleFilter.toLowerCase())),
    [teamPeople, peopleFilter],
  );

  const handleLoadSheetOptions = async () => {
    setLoadingOptions(true);
    setErrorMsg(null);
    try {
      const data = await api.parseSheetOptions(spreadsheetId);
      setTeams(data.teams || []);
      if (data.teams?.length && !data.teams.includes(selectedTeam)) setSelectedTeam(data.teams[0]);
    } catch (err) {
      setErrorMsg(`解析 Sheet 選項失敗：${err.message}`);
    } finally {
      setLoadingOptions(false);
    }
  };

  const handleLoadVideos = async () => {
    setLoadingVideos(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      const videoList = res.videos || [];
      setVideos(videoList);
      setSelectedVideoIds([]);
      setAssignments({});
      setPlaylistSource(res.source || '');
      setPlaylistFallbackReason(res.fallback_reason || '');
      setQuotaRefreshKey((key) => key + 1);
    } catch (err) {
      setErrorMsg(`載入草稿影片失敗：${err.message}`);
    } finally {
      setLoadingVideos(false);
    }
  };

  const handleLoadAll = async () => {
    if (!authUser) {
      toast.warning('請先在系統設定中連結 Google 帳號！');
      return;
    }
    await Promise.all([handleLoadSheetOptions(), handleLoadVideos()]);
  };

  const toggleVideo = (videoId) => {
    setSelectedVideoIds((current) => current.includes(videoId)
      ? current.filter((id) => id !== videoId)
      : [...current, videoId]);
    setAssignments((current) => ({ ...current, [videoId]: current[videoId] || '不編輯' }));
  };

  const setAllSelected = (checked) => {
    if (!checked) {
      setSelectedVideoIds([]);
      return;
    }
    setSelectedVideoIds(videos.map((video) => video.video_id));
    setAssignments((current) => {
      const next = { ...current };
      videos.forEach((video) => { if (!next[video.video_id]) next[video.video_id] = '不編輯'; });
      return next;
    });
  };

  const handleBatchSetPerson = (person) => {
    setAssignments((current) => {
      const next = { ...current };
      selectedVideoIds.forEach((videoId) => { next[videoId] = person; });
      return next;
    });
  };

  const doExecute = async () => {
    setConfirmOpen(false);
    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const payloadAssignments = selectedVideoIds.map((videoId) => ({
        video_id: videoId,
        person: assignments[videoId] || '不編輯',
      }));
      const res = await api.batchUpdateMetadata(
        spreadsheetId,
        playlistId,
        videoType,
        selectedTeam,
        payloadAssignments,
      );
      setResult(res);
      setQuotaRefreshKey((key) => key + 1);
      toast.success(`批次更新完成！成功 ${res.updated_count} 支、略過 ${res.skipped_count} 支`);
    } catch (err) {
      setErrorMsg(`批次更新執行失敗：${err.message}`);
      toast.error('批次更新執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const requestExecute = () => {
    if (!selectedTeam) return toast.warning('請先選擇所屬團體！');
    if (!selectedVideoIds.length) return toast.warning('請先勾選要編輯的影片！');
    setConfirmOpen(true);
  };

  const sourceLabel = playlistSource === 'yt-dlp'
    ? 'yt-dlp（不耗 API 配額）'
    : playlistSource === 'youtube-api'
      ? 'YouTube API 回退模式'
      : '';

  return (
    <div className="section-gap">
      <ConfirmDialog
        open={confirmOpen}
        title="確認批次更新"
        message={`確定要處理目前勾選的 ${selectedVideoIds.length} 支影片嗎？只有勾選項目會送出。`}
        confirmText="確認開始覆寫"
        cancelText="取消"
        variant="destructive"
        onConfirm={doExecute}
        onCancel={() => setConfirmOpen(false)}
      />

      <YouTubeQuotaBanner refreshKey={quotaRefreshKey} />

      <div>
        <div className="section-header"><Layers size={24} color="var(--primary)" /><h1 style={{ fontSize: '1.8rem' }}>YouTube 草稿影片｜批次套用標題與說明</h1></div>
        <p className="section-desc">先在播放清單篩選區勾選影片，下方編輯區只會顯示並處理已勾選的項目。</p>
      </div>

      <div className="top-filter-bar">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, color: '#fff' }}><SlidersHorizontal size={18} color="var(--primary)" /><span>篩選控制與選單欄位</span></div>
          <button className="btn btn-primary" onClick={handleLoadAll} disabled={loadingOptions || loadingVideos}>
            <RefreshCw size={16} className={loadingOptions || loadingVideos ? 'spin' : ''} />
            {loadingOptions || loadingVideos ? '載入中...' : '讀取 Sheet 選項與草稿影片'}
          </button>
        </div>

        <div className="top-filter-grid">
          <div className="form-group"><label className="form-label"><FileSpreadsheet size={14} /> 標題試算表 ID / URL</label><input className="form-input" value={spreadsheetId} onChange={(e) => setSpreadsheetId(e.target.value)} /></div>
          <div className="form-group"><label className="form-label"><PlaySquare size={14} /> 目標播放清單 ID</label><input className="form-input" value={playlistId} onChange={(e) => setPlaylistId(e.target.value)} /></div>
          <div className="form-group"><label className="form-label"><VideoIcon size={14} /> 影片類型</label><select className="form-select" value={videoType} onChange={(e) => setVideoType(e.target.value)}><option value="Video">Video</option><option value="Shorts">Shorts</option></select></div>
          <div className="form-group"><label className="form-label"><Users size={14} /> 所屬團體</label><select className="form-select" value={selectedTeam} onChange={(e) => setSelectedTeam(e.target.value)}>{teams.length ? teams.map((team) => <option key={team} value={team}>{team}</option>) : <option value="">請先讀取 Sheet</option>}</select></div>
          <div className="form-group"><label className="form-label"><Filter size={14} /> 搜尋人物</label><input className="form-input" value={peopleFilter} onChange={(e) => setPeopleFilter(e.target.value)} placeholder="搜尋人物姓名..." /></div>
        </div>
        <div className="info-banner"><Info size={14} color="var(--primary)" /><span>播放清單預覽優先使用 yt-dlp；縮圖直接使用 YouTube 靜態縮圖網址，不額外耗用 API 額度。</span></div>
      </div>

      {errorMsg && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{errorMsg}</span></div>}

      {videos.length > 0 && (
        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '14px' }}>
            <div><h2 style={{ fontSize: '1.2rem' }}><ListFilter size={19} style={{ verticalAlign: 'middle', marginRight: 7 }} />影片篩選（已選 {selectedVideoIds.length} / {videos.length}）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>來源：{sourceLabel}{playlistFallbackReason ? `；回退原因：${playlistFallbackReason}` : ''}</p></div>
            <label style={{ display: 'flex', gap: '8px', alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.length === videos.length && videos.length > 0} onChange={(e) => setAllSelected(e.target.checked)} /> 全選 / 全不選</label>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '10px' }}>
            {videos.map((video, index) => {
              const checked = selectedVideoIds.includes(video.video_id);
              return (
                <label key={video.video_id} className="glass-panel" style={{ padding: '12px', display: 'flex', gap: '10px', cursor: 'pointer', borderColor: checked ? 'var(--primary)' : undefined }}>
                  <input type="checkbox" checked={checked} onChange={() => toggleVideo(video.video_id)} style={{ marginTop: 4 }} />
                  {video.thumbnail_url && <img src={video.thumbnail_url} alt="" style={{ width: 96, aspectRatio: '16/9', objectFit: 'cover', borderRadius: 6 }} />}
                  <div style={{ minWidth: 0 }}><strong style={{ color: '#fff', fontSize: '0.84rem', display: 'block' }}>#{index + 1} {video.title || '無標題影片'}</strong><span style={{ color: 'var(--text-dim)', fontSize: '0.72rem' }}>{video.video_id}</span></div>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {selectedVideos.length > 0 && (
        <div className="section-gap" style={{ gap: '18px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <div><h2 style={{ fontSize: '1.3rem' }}><CheckSquare2 size={20} style={{ verticalAlign: 'middle', marginRight: 7 }} />編輯已勾選影片（{selectedVideos.length} 支）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>未勾選影片不會顯示，也不會送到後端。</p></div>
            <select className="form-select" style={{ width: 'auto' }} defaultValue="" onChange={(e) => e.target.value && handleBatchSetPerson(e.target.value)}><option value="" disabled>全部套用人物...</option><option value="不編輯">全部設為不編輯</option>{visiblePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select>
          </div>

          <div className="video-card-grid">
            {selectedVideos.map((video) => (
              <div key={video.video_id} className="glass-panel video-card">
                <div className="video-thumbnail-wrapper">{video.thumbnail_url ? <img className="video-thumbnail" src={video.thumbnail_url} alt={video.title} /> : <div>無縮圖</div>}</div>
                <div><h4 style={{ color: '#fff', fontSize: '0.95rem' }}>{video.title || '無標題影片'}</h4><p style={{ color: 'var(--text-dim)', fontSize: '0.76rem' }}>Video ID: {video.video_id}</p></div>
                <div className="form-group" style={{ marginTop: 'auto' }}><label className="form-label">指定套用人物</label><select className="form-select" value={assignments[video.video_id] || '不編輯'} onChange={(e) => setAssignments((current) => ({ ...current, [video.video_id]: e.target.value }))}><option value="不編輯">不編輯（略過）</option>{visiblePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
              </div>
            ))}
          </div>

          <div className="glass-panel execution-bar"><div><strong style={{ color: '#fff' }}>只處理目前勾選的 {selectedVideoIds.length} 支影片</strong><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>後端會先批次讀取影片資料，再執行必要的更新，減少 videos.list 呼叫。</p></div><button className="btn btn-success" onClick={requestExecute} disabled={executing}><Send size={18} /> {executing ? '批次更新中...' : '確認並開始覆寫'}</button></div>
        </div>
      )}

      {result && (
        <div className="glass-panel" style={{ padding: '24px' }}><h3 style={{ color: '#34d399', display: 'flex', gap: 8, alignItems: 'center' }}><CheckCircle2 size={22} /> 批次處理完成</h3><p style={{ color: 'var(--text-muted)' }}>成功 {result.updated_count}、略過 {result.skipped_count}、失敗 {result.failed_count}</p></div>
      )}
    </div>
  );
}

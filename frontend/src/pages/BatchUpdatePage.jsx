import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import {
  Layers,
  Filter,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Video as VideoIcon,
  Users,
  FileSpreadsheet,
  PlaySquare,
  Send,
  SlidersHorizontal,
  Info
} from 'lucide-react';

export default function BatchUpdatePage({ sysSettings, authUser }) {
  const toast = useToast();

  // Top Filter Bar state
  const [spreadsheetId, setSpreadsheetId] = useState(sysSettings.default_spreadsheet_id || '');
  const [playlistId, setPlaylistId] = useState(sysSettings.default_playlist_id || '');
  const [videoType, setVideoType] = useState('Video');
  const [selectedTeam, setSelectedTeam] = useState('');

  // Dynamic options loaded from Google Sheet
  const [teams, setTeams] = useState([]);
  const [teamPeople, setTeamPeople] = useState([]);

  // People filter
  const [peopleFilter, setPeopleFilter] = useState('');

  // Video list state
  const [videos, setVideos] = useState([]);
  const [assignments, setAssignments] = useState({});

  // UI states
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [loadingVideos, setLoadingVideos] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Sync settings when sysSettings loads
  useEffect(() => {
    if (sysSettings.default_spreadsheet_id && !spreadsheetId) {
      setSpreadsheetId(sysSettings.default_spreadsheet_id);
    }
    if (sysSettings.default_playlist_id && !playlistId) {
      setPlaylistId(sysSettings.default_playlist_id);
    }
  }, [sysSettings]);

  const handleLoadSheetOptions = async () => {
    if (!authUser) {
      toast.warning('請先在系統設定中連結 Google 帳號！');
      return;
    }
    setLoadingOptions(true);
    setErrorMsg(null);
    try {
      const data = await api.parseSheetOptions(spreadsheetId);
      setTeams(data.teams || []);
      if (data.teams && data.teams.length > 0 && !selectedTeam) {
        setSelectedTeam(data.teams[0]);
      }
    } catch (err) {
      setErrorMsg(`解析 Sheet 選項失敗：${err.message}`);
    } finally {
      setLoadingOptions(false);
    }
  };

  useEffect(() => {
    if (selectedTeam && authUser) {
      api.getTeamPeople(spreadsheetId, videoType, selectedTeam)
        .then((res) => {
          setTeamPeople(res.people || []);
        })
        .catch((err) => console.error("Error fetching people:", err));
    }
  }, [selectedTeam, videoType, spreadsheetId, authUser]);

  const handleLoadVideos = async () => {
    if (!authUser) {
      toast.warning('請先在系統設定中連結 Google 帳號！');
      return;
    }
    setLoadingVideos(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      const videoList = res.videos || [];
      setVideos(videoList);
      const initialMap = {};
      videoList.forEach((v) => { initialMap[v.video_id] = '不編輯'; });
      setAssignments(initialMap);
    } catch (err) {
      setErrorMsg(`載入草稿影片失敗：${err.message}`);
    } finally {
      setLoadingVideos(false);
    }
  };

  const handleLoadAll = async () => {
    await handleLoadSheetOptions();
    await handleLoadVideos();
  };

  const handleAssignmentChange = (videoId, person) => {
    setAssignments((prev) => ({ ...prev, [videoId]: person }));
  };

  const handleBatchSetPerson = (targetPerson) => {
    const updated = {};
    videos.forEach((v) => { updated[v.video_id] = targetPerson; });
    setAssignments(updated);
  };

  const handleExecuteBatchUpdate = async () => {
    if (!selectedTeam) {
      toast.warning('請先選擇「所屬團體」！');
      return;
    }
    setConfirmOpen(true);
  };

  const doExecute = async () => {
    setConfirmOpen(false);
    const payloadAssignments = Object.keys(assignments).map((vid) => ({
      video_id: vid,
      person: assignments[vid]
    }));

    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.batchUpdateMetadata(
        spreadsheetId, playlistId, videoType, selectedTeam, payloadAssignments
      );
      setResult(res);
      toast.success(`批次更新完成！成功 ${res.updated_count} 支、略過 ${res.skipped_count} 支`);
    } catch (err) {
      setErrorMsg(`批次更新執行失敗：${err.message}`);
      toast.error('批次更新執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const visiblePeople = teamPeople.filter((p) =>
    !peopleFilter || p.toLowerCase().includes(peopleFilter.toLowerCase())
  );

  return (
    <div className="section-gap">
      <ConfirmDialog
        open={confirmOpen}
        title="確認批次更新"
        message={`確定要為 ${Object.keys(assignments).length} 支影片執行 YouTube 標題與說明批次覆寫嗎？此操作無法自動還原。`}
        confirmText="確認開始覆寫"
        cancelText="取消"
        variant="destructive"
        onConfirm={doExecute}
        onCancel={() => setConfirmOpen(false)}
      />

      {/* Title */}
      <div>
        <div className="section-header">
          <Layers size={24} color="var(--primary)" />
          <h1 style={{ fontSize: '1.8rem' }}>YouTube 草稿影片｜批次套用標題與說明</h1>
        </div>
        <p className="section-desc">
          由 Google Sheet 即時讀取「Youtube Video / Shorts」工作表，依選取之團體與人物覆寫播放清單內草稿影片標題與說明。
        </p>
      </div>

      {/* TOP FILTER BAR */}
      <div className="top-filter-bar">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, color: '#fff' }}>
            <SlidersHorizontal size={18} color="var(--primary)" />
            <span>篩選控制與選單欄位 (Filter & Options Bar)</span>
          </div>
          <button className="btn btn-primary" onClick={handleLoadAll} disabled={loadingOptions || loadingVideos}>
            <RefreshCw size={16} className={loadingOptions || loadingVideos ? 'spin' : ''} />
            {loadingOptions || loadingVideos ? '載入中...' : '讀取 Sheet 選項與草稿影片'}
          </button>
        </div>

        <div className="top-filter-grid">
          <div className="form-group">
            <label className="form-label"><FileSpreadsheet size={14}/> 標題試算表 ID / URL</label>
            <input className="form-input" type="text" value={spreadsheetId}
              onChange={(e) => setSpreadsheetId(e.target.value)} placeholder="Google Sheet ID or URL" />
          </div>

          <div className="form-group">
            <label className="form-label"><PlaySquare size={14}/> 目標播放清單 ID</label>
            <input className="form-input" type="text" value={playlistId}
              onChange={(e) => setPlaylistId(e.target.value)} placeholder="YouTube Playlist ID" />
          </div>

          <div className="form-group">
            <label className="form-label"><VideoIcon size={14}/> 影片類型 (決定 Sheet 來源)</label>
            <select className="form-select" value={videoType} onChange={(e) => setVideoType(e.target.value)}>
              <option value="Video">Video (一般長影片)</option>
              <option value="Shorts">Shorts (短影片)</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label"><Users size={14}/> 所屬團體 (篩選人物)</label>
            <select className="form-select" value={selectedTeam} onChange={(e) => setSelectedTeam(e.target.value)}>
              {teams.length === 0 ? (
                <option value="">請先點擊「讀取 Sheet 選項」</option>
              ) : (
                teams.map((t) => (<option key={t} value={t}>{t}</option>))
              )}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label"><Filter size={14}/> 篩選人物選單 (People Search Filter)</label>
            <input className="form-input" type="text" placeholder="搜尋人物姓名..."
              value={peopleFilter} onChange={(e) => setPeopleFilter(e.target.value)} />
          </div>
        </div>

        <div className="info-banner">
          <Info size={14} color="var(--primary)"/>
          <span>
            {videoType === 'Video'
              ? '「Video」模式使用 Youtube Video 工作表的 Title 與 Description'
              : '「Shorts」模式使用 Youtube Shorts 工作表的 Title 與 Description'}。公開狀態與播放清單不會在此步驟被刪除或修改。
          </span>
        </div>
      </div>

      {/* Error Alert */}
      {errorMsg && (
        <div className="glass-panel error-alert">
          <AlertCircle size={20} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Draft Videos Section */}
      {videos.length > 0 && (
        <div className="section-gap" style={{ gap: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <h2 style={{ fontSize: '1.3rem' }}>草稿影片列表 (共 {videos.length} 支)</h2>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>依發布時間由舊到新排序。請為每支影片指定人物：</p>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'rgba(18, 24, 36, 0.7)', padding: '8px 14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', fontWeight: 600 }}>全套用人物:</span>
              <select className="form-select" style={{ padding: '4px 10px', fontSize: '0.85rem' }}
                onChange={(e) => { if (e.target.value) handleBatchSetPerson(e.target.value); }} defaultValue="">
                <option value="" disabled>快速一鍵全選...</option>
                <option value="不編輯">全設為：不編輯</option>
                {visiblePeople.map((p) => (<option key={p} value={p}>全設為：{p}</option>))}
              </select>
            </div>
          </div>

          <div className="video-card-grid">
            {videos.map((v) => {
              const currentPerson = assignments[v.video_id] || '不編輯';
              return (
                <div key={v.video_id} className="glass-panel video-card">
                  <div className="video-thumbnail-wrapper">
                    <span className="video-badge-seq">影片 #{v.sequence}</span>
                    {v.thumbnail_url ? (
                      <img className="video-thumbnail" src={v.thumbnail_url} alt={v.title} />
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-dim)' }}>
                        此影片無可用縮圖
                      </div>
                    )}
                  </div>

                  <div>
                    <h4 style={{ fontSize: '0.95rem', color: '#fff', marginBottom: '6px', overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', minHeight: '2.8em' }}>
                      {v.title || '無標題影片'}
                    </h4>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>Video ID: {v.video_id}</p>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>發布時間: {v.published_at ? new Date(v.published_at).toLocaleString() : '未提供'}</p>
                  </div>

                  <div className="form-group" style={{ marginTop: 'auto' }}>
                    <label className="form-label" style={{ color: 'var(--primary)' }}>指定套用人物：</label>
                    <select className="form-select" value={currentPerson}
                      onChange={(e) => handleAssignmentChange(v.video_id, e.target.value)}>
                      <option value="不編輯">不編輯 (略過)</option>
                      {visiblePeople.map((p) => (<option key={p} value={p}>{p}</option>))}
                    </select>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Bottom Execution Bar */}
          <div className="glass-panel execution-bar" style={{ marginTop: '12px' }}>
            <div>
              <span style={{ fontSize: '0.9rem', color: '#fff', fontWeight: 600 }}>準備執行批次更新</span>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                將比對「{selectedTeam}」的對應人物資料，並安全寫入 YouTube 標題與說明。
              </p>
            </div>
            <button className="btn btn-success" style={{ padding: '12px 32px', fontSize: '1.05rem' }}
              onClick={handleExecuteBatchUpdate} disabled={executing}>
              <Send size={18} /> {executing ? '批次更新中...' : '確認並開始覆寫 YouTube 資訊'}
            </button>
          </div>
        </div>
      )}

      {/* Execution Results */}
      {result && (
        <div className="glass-panel" style={{ padding: '24px', border: '1px solid var(--primary-glow)', background: 'rgba(15, 23, 42, 0.95)' }}>
          <h3 style={{ fontSize: '1.3rem', color: '#34d399', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <CheckCircle2 size={22}/> YouTube 草稿資料批次處理完成！
          </h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
            本批次總計處理 {result.total_processed} 支影片。成功更新：{result.updated_count} 支、略過：{result.skipped_count} 支、失敗：{result.failed_count} 支。
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '300px', overflowY: 'auto' }}>
            {result.results.map((r, idx) => (
              <div key={idx} className={`result-item ${r.status === 'updated' ? 'result-item-success' : r.status === 'failed' ? 'result-item-failed' : 'result-item-skipped'}`}>
                <div>
                  <strong style={{ color: '#fff' }}>Video ID: {r.video_id}</strong> (人物: {r.person})
                  {r.new_title && <div style={{ color: '#a5b4fc', fontSize: '0.8rem', marginTop: '2px' }}>新標題: {r.new_title}</div>}
                  {r.reason && <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '2px' }}>原因: {r.reason}</div>}
                </div>
                <span className={`badge ${r.status === 'updated' ? 'badge-connected' : r.status === 'failed' ? 'badge-disconnected' : 'badge-info'}`}>
                  {r.status === 'updated' ? '已更新' : r.status === 'failed' ? '更新失敗' : '已略過'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

import React, { useEffect, useState } from 'react';
import { CheckSquare, RefreshCw, Send } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';

const STATUS_LABELS = {
  queued: '排隊中',
  uploaded: '已上傳 R2',
  container_created: '已建立 Instagram container',
  published: '已發布',
  failed: '失敗',
  paused: '已暫停',
  skipped: '已略過',
};

export default function InstagramReelsPage() {
  const toast = useToast();
  const [config, setConfig] = useState({ drive_folder_id: '', spreadsheet_id: '', worksheet_name: '', caption_column: '', team: '', share_to_feed: true });
  const [worksheets, setWorksheets] = useState([]);
  const [teams, setTeams] = useState([]);
  const [people, setPeople] = useState([]);
  const [videos, setVideos] = useState([]);
  const [assignments, setAssignments] = useState({});
  const [bulkPerson, setBulkPerson] = useState('');
  const [selected, setSelected] = useState([]);
  const [publishing, setPublishing] = useState(false);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [job, setJob] = useState(null);
  const worksheet = worksheets.find((item) => item.title === config.worksheet_name);

  useEffect(() => {
    api.getInstagramSettings()
      .then((data) => setConfig((old) => ({ ...old, drive_folder_id: data.drive_folder_id || '', spreadsheet_id: data.spreadsheet_id || '' })))
      .catch(() => {});
  }, []);

  const loadSheet = async () => {
    try {
      const data = await api.getSpreadsheetMetadata(config.spreadsheet_id);
      setWorksheets(data.worksheets || []);
      setConfig((current) => ({ ...current, worksheet_name: '', caption_column: '', team: '' }));
      setTeams([]);
      setPeople([]);
      setAssignments({});
      setSelected([]);
      toast.success('工作表已刷新');
    } catch (error) { toast.error(error.message); }
  };

  const loadTeams = async (name) => {
    setConfig((current) => ({ ...current, worksheet_name: name, caption_column: '', team: '' }));
    setPeople([]);
    setAssignments({});
    setSelected([]);
    try {
      const data = await api.parseSheetOptions(config.spreadsheet_id, name);
      setTeams(data.teams || []);
    } catch (error) { toast.error(error.message); }
  };

  const loadPeople = async (team) => {
    setConfig((current) => ({ ...current, team }));
    setAssignments({});
    setSelected([]);
    try {
      const data = await api.getTeamPeople(config.spreadsheet_id, config.worksheet_name, team);
      setPeople(data.people || data || []);
    } catch (error) { toast.error(error.message); }
  };

  const loadVideos = async () => {
    try {
      const data = await api.getInstagramDriveVideos(config.drive_folder_id);
      setVideos(data.videos || []);
      setJob(null);
      toast.success(`已讀取 ${data.total || 0} 支影片`);
    } catch (error) { toast.error(error.message); }
  };

  const applyBulk = () => {
    setAssignments((old) => ({ ...old, ...Object.fromEntries(selected.map((id) => [id, bulkPerson])) }));
    setSelected([]);
  };

  const publish = async () => {
    const active = videos.filter((video) => assignments[video.id]).map((video) => ({ file_id: video.id, person: assignments[video.id] }));
    if (!active.length) { toast.warning('請先指定人物'); return; }
    setConfirmPublish(false);
    setPublishing(true);
    try {
      const result = await api.createInstagramPublishJob({
        drive_folder_url_or_id: config.drive_folder_id,
        spreadsheet_url_or_id: config.spreadsheet_id,
        worksheet_name: config.worksheet_name,
        caption_column: config.caption_column,
        team: config.team,
        share_to_feed: config.share_to_feed,
        assignments: active,
      });
      setJob(result);
      if (result.status === 'paused') toast.error('發布已暫停，請查看逐片結果或重試。');
      else toast.success(`發布工作完成：成功 ${result.published_count}、略過 ${result.skipped_count}`);
    } catch (error) { toast.error(error.message); } finally { setPublishing(false); }
  };

  const reloadJob = async () => {
    if (!job?.id) return;
    try { setJob(await api.getInstagramPublishJob(job.id)); } catch (error) { toast.error(error.message); }
  };

  const retryJob = async () => {
    if (!job?.id) return;
    setPublishing(true);
    try { setJob(await api.retryInstagramPublishJob(job.id)); } catch (error) { toast.error(error.message); } finally { setPublishing(false); }
  };

  const columns = worksheet?.columns || [];
  return <div className="section-gap">
    <div><h1>Instagram Reels 自動發布</h1><p className="section-desc">Drive 影片依建立時間由舊到新；工作結果會持久化，第一片失敗會暫停後續影片。</p></div>
    <div className="glass-panel card-padding" style={{ display: 'grid', gap: 14 }}>
      <input className="form-input" placeholder="Drive 資料夾 ID／網址" value={config.drive_folder_id} onChange={(e) => setConfig({ ...config, drive_folder_id: e.target.value })} />
      <div style={{ display: 'flex', gap: 8 }}><input className="form-input" placeholder="Google Sheet ID／網址" value={config.spreadsheet_id} onChange={(e) => setConfig({ ...config, spreadsheet_id: e.target.value })} /><button className="btn btn-primary" onClick={loadSheet}><RefreshCw size={16} />刷新</button></div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        <select className="form-input" value={config.worksheet_name} onChange={(e) => loadTeams(e.target.value)}><option value="">選工作表</option>{worksheets.map((item) => <option key={item.title}>{item.title}</option>)}</select>
        <select className="form-input" value={config.caption_column} onChange={(e) => setConfig({ ...config, caption_column: e.target.value })}><option value="">選 Instagram 內文欄</option>{columns.map((column) => <option key={column}>{column}</option>)}</select>
        <select className="form-input" value={config.team} onChange={(e) => loadPeople(e.target.value)}><option value="">選團體</option>{teams.map((team) => <option key={team}>{team}</option>)}</select>
      </div>
      <label><input type="checkbox" checked={config.share_to_feed} onChange={(e) => setConfig({ ...config, share_to_feed: e.target.checked })} /> 同時分享到動態消息</label>
      <button className="btn btn-primary" onClick={loadVideos}><RefreshCw size={16} />讀取 Drive 影片</button>
    </div>
    {videos.length > 0 && <div className="glass-panel card-padding">
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}><select className="form-input" value={bulkPerson} onChange={(e) => setBulkPerson(e.target.value)}><option value="">批量選人物</option>{people.map((person) => <option key={person}>{person}</option>)}</select><button className="btn btn-primary" disabled={!bulkPerson || !selected.length} onClick={applyBulk}><CheckSquare size={16} />套用至已勾選</button></div>
      <div style={{ display: 'grid', gap: 8 }}>{videos.map((video, index) => <div key={video.id} className="glass-panel" style={{ padding: 12, display: 'grid', gridTemplateColumns: '36px 1fr 260px', gap: 10, alignItems: 'center' }}><input type="checkbox" checked={selected.includes(video.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, video.id] : selected.filter((id) => id !== video.id))} /><div><strong>{index + 1}. {video.name}</strong><div className="section-desc">{video.created_time} · {video.width || '?'}×{video.height || '?'} · {video.duration_seconds ? `${video.duration_seconds.toFixed(1)} 秒` : 'duration 未提供'}</div></div><select className="form-input" value={assignments[video.id] || ''} onChange={(e) => setAssignments({ ...assignments, [video.id]: e.target.value })}><option value="">不發布</option>{people.map((person) => <option key={person}>{person}</option>)}</select></div>)}</div>
      <button className="btn btn-success" style={{ marginTop: 14 }} onClick={() => setConfirmPublish(true)} disabled={publishing}><Send size={17} />{publishing ? '處理中…' : '建立發布工作'}</button>
    </div>}
    {job && <section className="glass-panel card-padding" style={{ display: 'grid', gap: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}><div><h2>發布工作 {job.status === 'paused' ? '已暫停' : '結果'}</h2><p className="section-desc">Job ID：{job.id}</p>{job.r2_cleanup_failed_count > 0 && <p className="section-desc" style={{ color: '#fbbf24' }}>有 {job.r2_cleanup_failed_count} 支影片尚未從 R2 清理，可重試清理。</p>}</div><div style={{ display: 'flex', gap: 8 }}><button className="btn btn-secondary" onClick={reloadJob}><RefreshCw size={16} />重新讀取</button>{(job.status === 'paused' || job.r2_cleanup_failed_count > 0) && <button className="btn btn-primary" onClick={retryJob} disabled={publishing}><Send size={16} />重試未完成項目</button>}</div></div>{job.results?.map((item) => <div key={`${item.file_id}-${item.sequence}`} className="glass-panel" style={{ padding: 12, display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}><div><strong>{item.sequence}. {item.file_name || item.file_id}</strong><p className="section-desc">{item.person} · {STATUS_LABELS[item.status] || item.status}</p>{item.error && <p style={{ color: '#f87171' }}>錯誤：{item.error}</p>}{item.r2_delete_error && <p style={{ color: '#fbbf24' }}>R2：{item.r2_delete_error}</p>}{item.r2_deleted && <p className="section-desc">R2 暫存影片已刪除</p>}{item.preflight && <p className="section-desc">{item.preflight.width || '?'}×{item.preflight.height || '?'} · {item.preflight.duration_seconds ? `${item.preflight.duration_seconds} 秒` : 'duration 未提供'} · {item.preflight.size_bytes || 0} bytes</p>}</div><span className={`badge ${item.status === 'published' ? 'badge-connected' : item.status === 'failed' ? 'badge-disconnected' : 'badge-info'}`}>{STATUS_LABELS[item.status] || item.status}</span></div>)}</section>}
    <ConfirmDialog open={confirmPublish} title="建立 Instagram 發布工作" message={`將依 Drive 建立時間由舊到新處理 ${videos.filter((video) => assignments[video.id]).length} 支 Reels，確定繼續？`} confirmText="開始處理" onConfirm={publish} onCancel={() => setConfirmPublish(false)} />
  </div>;
}

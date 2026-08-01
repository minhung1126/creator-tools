import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckSquare, FileSpreadsheet, Info, RefreshCw, Send, Users } from 'lucide-react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import ThumbnailDialog from '../components/ThumbnailDialog';

const STATUS_LABELS = {
  queued: '排隊中',
  uploaded: '已上傳 R2',
  container_created: '已建立 Instagram container',
  published: '已發布',
  failed: '失敗',
  paused: '已暫停',
  skipped: '已略過',
};

const DEFAULT_WORKSHEET = 'Insta Reels';
const DEFAULT_CAPTION_COLUMN = 'Reels Content';
const STORAGE_KEY = 'instagram-reels-config-v1';

function readRememberedConfig() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

function formatVideoMeta(video) {
  const dimensions = video.width && video.height ? `${video.width}×${video.height}` : '尺寸未提供';
  const duration = video.duration_seconds ? `${video.duration_seconds.toFixed(1)} 秒` : 'duration 未提供';
  return `${video.created_time || '建立時間未提供'} · ${dimensions} · ${duration}`;
}

export default function InstagramReelsPage() {
  const toast = useToast();
  const remembered = useMemo(readRememberedConfig, []);
  const [config, setConfig] = useState({
    drive_folder_id: remembered.drive_folder_id || '',
    spreadsheet_id: remembered.spreadsheet_id || '',
    worksheet_name: remembered.worksheet_name || '',
    caption_column: remembered.caption_column || '',
    team: remembered.team || '',
    share_to_feed: remembered.share_to_feed ?? true,
  });
  const [worksheets, setWorksheets] = useState([]);
  const [columns, setColumns] = useState([]);
  const [teams, setTeams] = useState([]);
  const [people, setPeople] = useState([]);
  const [enabledPeople, setEnabledPeople] = useState([]);
  const [videos, setVideos] = useState([]);
  const [assignments, setAssignments] = useState({});
  const [selectedVideoIds, setSelectedVideoIds] = useState([]);
  const [bulkPerson, setBulkPerson] = useState('');
  const [peopleReloadKey, setPeopleReloadKey] = useState(0);
  const [loadingSheet, setLoadingSheet] = useState(false);
  const [loadingVideos, setLoadingVideos] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [job, setJob] = useState(null);
  const [previewImage, setPreviewImage] = useState(null);

  const updateConfig = (patch) => setConfig((current) => ({ ...current, ...patch }));
  const selectedWorksheet = worksheets.find((item) => item.title === config.worksheet_name);
  const availablePeople = useMemo(
    () => people.filter((person) => enabledPeople.includes(person)),
    [people, enabledPeople],
  );

  useEffect(() => {
    api.getInstagramSettings()
      .then((data) => setConfig((current) => ({
        ...current,
        drive_folder_id: data.drive_folder_id || current.drive_folder_id,
        spreadsheet_id: data.spreadsheet_id || current.spreadsheet_id,
      })))
      .catch(() => {});
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  }, [config]);

  useEffect(() => {
    if (!config.team || !config.worksheet_name || !config.spreadsheet_id) {
      setPeople([]);
      setEnabledPeople([]);
      return undefined;
    }
    let cancelled = false;
    api.getTeamPeople(config.spreadsheet_id, config.worksheet_name, config.team)
      .then((data) => {
        if (cancelled) return;
        const nextPeople = data.people || data || [];
        setPeople(nextPeople);
        setEnabledPeople(nextPeople);
      })
      .catch((error) => {
        if (!cancelled) setErrorMsg(`讀取人物失敗：${error.message}`);
      });
    return () => { cancelled = true; };
  }, [config.spreadsheet_id, config.worksheet_name, config.team, peopleReloadKey]);

  const resetVideoAssignments = () => {
    setAssignments({});
    setSelectedVideoIds([]);
    setBulkPerson('');
  };

  const chooseWorksheet = async (worksheetName, currentTeam = config.team) => {
    const nextWorksheet = worksheets.find((item) => item.title === worksheetName);
    const nextColumns = nextWorksheet?.columns || [];
    const nextCaptionColumn = nextColumns.includes(config.caption_column)
      ? config.caption_column
      : nextColumns.includes(DEFAULT_CAPTION_COLUMN)
        ? DEFAULT_CAPTION_COLUMN
        : nextColumns[0] || '';

    setColumns(nextColumns);
    setTeams([]);
    setPeople([]);
    setEnabledPeople([]);
    resetVideoAssignments();
    setErrorMsg('');
    updateConfig({ worksheet_name: worksheetName, caption_column: nextCaptionColumn, team: '' });
    if (!worksheetName) return;

    try {
      const data = await api.parseSheetOptions(config.spreadsheet_id, worksheetName);
      const nextTeams = data.teams || [];
      const nextTeam = nextTeams.includes(currentTeam) ? currentTeam : nextTeams[0] || '';
      setTeams(nextTeams);
      updateConfig({ team: nextTeam });
      setPeopleReloadKey((key) => key + 1);
    } catch (error) {
      setErrorMsg(`讀取工作表選項失敗：${error.message}`);
    }
  };

  const loadSheet = async () => {
    if (!config.spreadsheet_id.trim()) {
      toast.warning('請先填寫 Google Sheet ID／網址');
      return;
    }
    setLoadingSheet(true);
    setErrorMsg('');
    try {
      const data = await api.getSpreadsheetMetadata(config.spreadsheet_id);
      const nextWorksheets = data.worksheets || [];
      setWorksheets(nextWorksheets);
      const nextWorksheet = nextWorksheets.some((sheet) => sheet.title === config.worksheet_name)
        ? config.worksheet_name
        : nextWorksheets.some((sheet) => sheet.title === DEFAULT_WORKSHEET)
          ? DEFAULT_WORKSHEET
          : nextWorksheets[0]?.title || '';
      const nextSheet = nextWorksheets.find((sheet) => sheet.title === nextWorksheet);
      const nextColumns = nextSheet?.columns || [];
      const nextCaptionColumn = nextColumns.includes(config.caption_column)
        ? config.caption_column
        : nextColumns.includes(DEFAULT_CAPTION_COLUMN)
          ? DEFAULT_CAPTION_COLUMN
          : nextColumns[0] || '';
      const options = nextWorksheet
        ? await api.parseSheetOptions(config.spreadsheet_id, nextWorksheet)
        : { teams: [] };
      const nextTeams = options.teams || [];
      const nextTeam = nextTeams.includes(config.team) ? config.team : nextTeams[0] || '';

      setColumns(nextColumns);
      setTeams(nextTeams);
      setPeople([]);
      setEnabledPeople([]);
      resetVideoAssignments();
      updateConfig({ worksheet_name: nextWorksheet, caption_column: nextCaptionColumn, team: nextTeam });
      setPeopleReloadKey((key) => key + 1);
      toast.success('工作表與欄位已刷新');
    } catch (error) {
      setErrorMsg(`刷新試算表失敗：${error.message}`);
      toast.error(error.message);
    } finally {
      setLoadingSheet(false);
    }
  };

  const handleWorksheetChange = async (event) => {
    await chooseWorksheet(event.target.value);
  };

  const handleTeamChange = (event) => {
    updateConfig({ team: event.target.value });
    setPeople([]);
    setEnabledPeople([]);
    resetVideoAssignments();
  };

  const togglePerson = (person) => {
    const nextPeople = enabledPeople.includes(person)
      ? enabledPeople.filter((item) => item !== person)
      : [...enabledPeople, person];
    setEnabledPeople(nextPeople);
    if (!nextPeople.includes(person)) {
      setAssignments((current) => Object.fromEntries(
        Object.entries(current).filter(([, assignedPerson]) => nextPeople.includes(assignedPerson)),
      ));
    }
  };

  const setAllPeople = (checked) => {
    const nextPeople = checked ? [...people] : [];
    setEnabledPeople(nextPeople);
    if (!checked) setAssignments({});
  };

  const loadVideos = async () => {
    if (!config.drive_folder_id.trim()) {
      toast.warning('請先填寫 Drive 資料夾 ID／網址');
      return;
    }
    setLoadingVideos(true);
    setErrorMsg('');
    setJob(null);
    try {
      const data = await api.getInstagramDriveVideos(config.drive_folder_id);
      setVideos(data.videos || []);
      resetVideoAssignments();
      toast.success(`已讀取 ${data.total || 0} 支影片`);
    } catch (error) {
      setErrorMsg(`讀取 Drive 影片失敗：${error.message}`);
      toast.error(error.message);
    } finally {
      setLoadingVideos(false);
    }
  };

  const toggleVideoSelection = (videoId) => setSelectedVideoIds((current) => current.includes(videoId)
    ? current.filter((item) => item !== videoId)
    : [...current, videoId]);

  const setAllVideosSelected = (checked) => {
    setSelectedVideoIds(checked ? videos.map((video) => video.id) : []);
  };

  const applyBulk = () => {
    if (!selectedVideoIds.length) return toast.warning('請先勾選要批量指定人物的影片');
    if (!bulkPerson) return toast.warning('請先選擇要套用的人物');
    setAssignments((current) => ({
      ...current,
      ...Object.fromEntries(selectedVideoIds.map((id) => [id, bulkPerson])),
    }));
    setSelectedVideoIds([]);
    setBulkPerson('');
    toast.success(`已套用到 ${selectedVideoIds.length} 支影片，尚未送出`);
  };

  const publish = async () => {
    const active = videos
      .filter((video) => assignments[video.id])
      .map((video) => ({ file_id: video.id, person: assignments[video.id] }));
    if (!config.worksheet_name || !config.caption_column) {
      toast.warning('請先選擇工作表與 Reels Content 內文欄');
      return;
    }
    if (!config.team) {
      toast.warning('請先選擇所屬團體');
      return;
    }
    if (!active.length) {
      toast.warning('請至少為一支影片指定人物');
      return;
    }
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
    } catch (error) {
      toast.error(error.message);
    } finally {
      setPublishing(false);
    }
  };

  const reloadJob = async () => {
    if (!job?.id) return;
    try {
      setJob(await api.getInstagramPublishJob(job.id));
    } catch (error) {
      toast.error(error.message);
    }
  };

  const retryJob = async () => {
    if (!job?.id) return;
    setPublishing(true);
    try {
      setJob(await api.retryInstagramPublishJob(job.id));
    } catch (error) {
      toast.error(error.message);
    } finally {
      setPublishing(false);
    }
  };

  const assignedCount = videos.filter((video) => assignments[video.id]).length;
  return <div className="section-gap">
    <div>
      <h1>Instagram Reels 自動發布</h1>
      <p className="section-desc">先設定 Reels 的工作表與內文欄，再在獨立區塊篩選團體和人物。Drive 影片依建立時間由舊到新處理。</p>
    </div>

    <section className="top-filter-bar">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', borderBottom: '1px solid var(--border-color)', paddingBottom: 12 }}>
        <strong style={{ color: '#fff' }}><FileSpreadsheet size={17} style={{ verticalAlign: 'middle', marginRight: 7 }} />Reels 資料來源與內文欄位</strong>
        <button className="btn btn-primary" onClick={loadSheet} disabled={loadingSheet}><RefreshCw size={16} className={loadingSheet ? 'spin' : ''} />{loadingSheet ? '刷新中...' : '刷新工作表與欄位'}</button>
      </div>
      <div className="top-filter-grid">
        <div className="form-group"><label className="form-label">Reels Drive 資料夾 ID／網址</label><input className="form-input" value={config.drive_folder_id} onChange={(event) => updateConfig({ drive_folder_id: event.target.value })} placeholder="Google Drive 資料夾 ID／網址" /></div>
        <div className="form-group"><label className="form-label">Google Sheet ID／網址</label><input className="form-input" value={config.spreadsheet_id} onChange={(event) => updateConfig({ spreadsheet_id: event.target.value })} placeholder="Google Sheet ID／網址" /></div>
        <div className="form-group"><label className="form-label">Insta Reels 工作表</label><select className="form-select" value={config.worksheet_name} onChange={handleWorksheetChange}><option value="">請先刷新工作表</option>{worksheets.map((sheet) => <option key={sheet.title} value={sheet.title}>{sheet.title}</option>)}</select></div>
        <div className="form-group"><label className="form-label">Reels Content 內文欄</label><select className="form-select" value={config.caption_column} onChange={(event) => updateConfig({ caption_column: event.target.value })} disabled={!selectedWorksheet}><option value="">請選擇內文欄</option>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></div>
      </div>
      <div className="info-banner"><Info size={15} color="var(--primary)" /><span>這裡只管理工作表與欄位；團體和人物篩選在下方獨立設定。</span></div>
    </section>

    <section className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
      <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: 12 }}>
        <strong style={{ color: '#fff' }}><Users size={17} style={{ verticalAlign: 'middle', marginRight: 7 }} />團體與人物篩選</strong>
        <p className="section-desc" style={{ marginTop: 7 }}>先選團體，再勾選要出現在每支 Reels 人物下拉選單中的人物；這個邏輯與 YouTube 草稿一致。</p>
      </div>
      <div className="form-group" style={{ maxWidth: 360 }}><label className="form-label">所屬團體</label><select className="form-select" value={config.team} onChange={handleTeamChange} disabled={!teams.length}><option value="">{teams.length ? '請選擇團體' : '請先選擇工作表'}</option>{teams.map((team) => <option key={team} value={team}>{team}</option>)}</select></div>
      {people.length > 0 && <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
          <div><h2 style={{ fontSize: '1.1rem' }}>人物選項篩選（已啟用 {enabledPeople.length} / {people.length}）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 5 }}>只有勾選的人物會出現在下方每支影片的指定人物選單中。</p></div>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={enabledPeople.length === people.length} onChange={(event) => setAllPeople(event.target.checked)} /> 全選 / 全不選</label>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>{people.map((person) => <label key={person} className="glass-panel" style={{ padding: 12, display: 'flex', gap: 9, alignItems: 'center', cursor: 'pointer', borderColor: enabledPeople.includes(person) ? 'var(--primary)' : undefined }}><input type="checkbox" checked={enabledPeople.includes(person)} onChange={() => togglePerson(person)} /><span style={{ color: '#fff' }}>{person}</span></label>)}</div>
      </div>}
      {config.team && !people.length && !errorMsg && <p className="section-desc">正在讀取團體人物…</p>}
      <label><input type="checkbox" checked={config.share_to_feed} onChange={(event) => updateConfig({ share_to_feed: event.target.checked })} /> 同時分享到動態消息</label>
    </section>

    {errorMsg && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{errorMsg}</span></div>}

    <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button className="btn btn-primary" onClick={loadVideos} disabled={loadingVideos}><RefreshCw size={16} className={loadingVideos ? 'spin' : ''} />{loadingVideos ? '載入中...' : '讀取 Drive 影片'}</button></div>

    {videos.length > 0 && <div className="section-gap" style={{ gap: 18 }}>
      <div><h2 style={{ fontSize: '1.3rem' }}>為每支影片指定人物（{videos.length} 支）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>只有上方啟用的人物會顯示在每支影片的選單中；未指定人物的影片不會發布。</p></div>
      <div className="glass-panel bulk-edit-panel" style={{ padding: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div><h3 style={{ color: '#fff', fontSize: '1.05rem' }}>批量指定人物（已勾選 {selectedVideoIds.length} 支）</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>只會套用到已勾選影片，套用後會自動清除勾選。</p></div>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.length === videos.length} onChange={(event) => setAllVideosSelected(event.target.checked)} /> 全選 / 全不選</label>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 14 }}>
          <div className="form-group" style={{ flex: '1 1 240px' }}><label className="form-label">批量套用人物</label><select className="form-select" value={bulkPerson} onChange={(event) => setBulkPerson(event.target.value)}><option value="">請選擇人物</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
          <button className="btn btn-primary" onClick={applyBulk} disabled={!selectedVideoIds.length || !bulkPerson}><CheckSquare size={16} />套用到已勾選影片</button>
        </div>
      </div>

      <div className="video-card-grid">{videos.map((video, index) => <div key={video.id} className={`glass-panel video-card ${assignments[video.id] ? 'video-card-assigned' : 'video-card-skipped'}`} style={{ borderColor: selectedVideoIds.includes(video.id) ? 'var(--primary)' : undefined }}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.includes(video.id)} onChange={() => toggleVideoSelection(video.id)} /> 加入批量指定</label>
        <div className="video-thumbnail-wrapper" style={{ aspectRatio: video.width && video.height ? `${video.width} / ${video.height}` : '9 / 16', maxHeight: 380 }}>
          {video.thumbnail_url ? <img className="video-thumbnail" src={video.thumbnail_url} alt={`${index + 1}. ${video.name}`} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.name })} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setPreviewImage({ src: video.thumbnail_url, alt: video.name }); }} role="button" tabIndex={0} /> : <div className="section-desc">Drive 沒有提供縮圖</div>}
        </div>
        <div><h4 style={{ color: '#fff', fontSize: '0.95rem' }}>{index + 1}. {video.name || '未命名影片'}</h4><p style={{ color: 'var(--text-dim)', fontSize: '0.76rem' }}>{formatVideoMeta(video)}</p></div>
        <div className="form-group" style={{ marginTop: 'auto' }}><label className="form-label">指定套用人物</label><select className="form-select" value={assignments[video.id] || ''} onChange={(event) => setAssignments((current) => ({ ...current, [video.id]: event.target.value }))}><option value="">不發布</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
      </div>)}</div>
      <div className="glass-panel execution-bar"><div><strong style={{ color: '#fff' }}>將處理目前清單中的 {assignedCount} 支影片</strong><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>人物為「不發布」的影片會安全略過。</p></div><button className="btn btn-success" onClick={() => setConfirmPublish(true)} disabled={publishing || !assignedCount}><Send size={18} />{publishing ? '處理中…' : '建立發布工作'}</button></div>
    </div>}

    {job && <section className="glass-panel card-padding" style={{ display: 'grid', gap: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}><div><h2>發布工作 {job.status === 'paused' ? '已暫停' : '結果'}</h2><p className="section-desc">Job ID：{job.id}</p>{job.r2_cleanup_failed_count > 0 && <p className="section-desc" style={{ color: '#fbbf24' }}>有 {job.r2_cleanup_failed_count} 支影片尚未從 R2 清理，可重試清理。</p>}</div><div style={{ display: 'flex', gap: 8 }}><button className="btn btn-secondary" onClick={reloadJob}><RefreshCw size={16} />重新讀取</button>{(job.status === 'paused' || job.r2_cleanup_failed_count > 0) && <button className="btn btn-primary" onClick={retryJob} disabled={publishing}><Send size={16} />重試未完成項目</button>}</div></div>{job.results?.map((item) => <div key={`${item.file_id}-${item.sequence}`} className="glass-panel" style={{ padding: 12, display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}><div><strong>{item.sequence}. {item.file_name || item.file_id}</strong><p className="section-desc">{item.person} · {STATUS_LABELS[item.status] || item.status}</p>{item.error && <p style={{ color: '#f87171' }}>錯誤：{item.error}</p>}{item.r2_delete_error && <p style={{ color: '#fbbf24' }}>R2：{item.r2_delete_error}</p>}{item.r2_deleted && <p className="section-desc">R2 暫存影片已刪除</p>}{item.preflight && <p className="section-desc">{item.preflight.width || '?'}×{item.preflight.height || '?'} · {item.preflight.duration_seconds ? `${item.preflight.duration_seconds} 秒` : 'duration 未提供'} · {item.preflight.size_bytes || 0} bytes</p>}</div><span className={`badge ${item.status === 'published' ? 'badge-connected' : item.status === 'failed' ? 'badge-disconnected' : 'badge-info'}`}>{STATUS_LABELS[item.status] || item.status}</span></div>)}</section>}
    <ConfirmDialog open={confirmPublish} title="建立 Instagram 發布工作" message={`將依 Drive 建立時間由舊到新處理 ${assignedCount} 支 Reels，確定繼續？`} confirmText="開始處理" onConfirm={publish} onCancel={() => setConfirmPublish(false)} />
    <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
  </div>;
}

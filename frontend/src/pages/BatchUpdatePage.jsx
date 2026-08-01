import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import { useActivityCenter } from '../hooks/useActivityCenter';
import ConfirmDialog from '../components/ConfirmDialog';
import TaskDetail from '../components/TaskDetail';
import YouTubeQuotaBanner from '../components/YouTubeQuotaBanner';
import ThumbnailDialog from '../components/ThumbnailDialog';
import SourceLinkInput from '../components/SourceLinkInput';
import { sortVideosByUploadTime } from '../utils/videoOrder';
import {
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  Info,
  PlaySquare,
  RefreshCw,
  Send,
  Shuffle,
  Users,
  Video as VideoIcon,
} from 'lucide-react';

const DEFAULT_COLUMNS = {
  Video: { title: 'Youtube Title', description: 'Youtube Description', worksheet: 'Youtube Video' },
  Shorts: { title: 'Shorts Title', description: 'Shorts Description', worksheet: 'Youtube Shorts' },
};

const storageKey = (videoType) => `youtube-draft-config-${videoType.toLowerCase()}`;

function readRemembered(videoType) {
  try {
    return JSON.parse(localStorage.getItem(storageKey(videoType)) || '{}');
  } catch {
    return {};
  }
}

function normalizeConfig(raw, defaults, sysSettings) {
  const enabledPeople = raw?.enabledPeople ?? raw?.enabled_people;
  return {
    spreadsheetId: raw?.spreadsheetId || raw?.spreadsheet_id || sysSettings.default_spreadsheet_id || '',
    playlistId: raw?.playlistId || raw?.playlist_id || sysSettings.default_playlist_id || '',
    worksheetName: raw?.worksheetName || raw?.worksheet_name || defaults.worksheet,
    titleColumn: raw?.titleColumn || raw?.title_column || defaults.title,
    descriptionColumn: raw?.descriptionColumn || raw?.description_column || defaults.description,
    selectedTeam: raw?.selectedTeam || raw?.team || '',
    enabledPeople: Array.isArray(enabledPeople) ? enabledPeople : [],
  };
}

function PreviewField({ label, value }) {
  const hasValue = value !== null && value !== undefined && String(value).trim() !== '';
  return (
    <div className="glass-panel" style={{ padding: 14 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: 7 }}>{label}</div>
      <div style={{ color: hasValue ? '#fff' : '#fbbf24', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.5 }}>
        {hasValue ? String(value) : '此欄位目前是空白，請記得編輯試算表'}
      </div>
    </div>
  );
}

export default function BatchUpdatePage({ sysSettings, authUser, videoType = 'Video', setActiveTab }) {
  const toast = useToast();
  const { refresh, tasks, cancelTask, retryTask } = useActivityCenter();
  const defaults = DEFAULT_COLUMNS[videoType];
  const initial = normalizeConfig(readRemembered(videoType), defaults, sysSettings);

  const [spreadsheetId, setSpreadsheetId] = useState(initial.spreadsheetId);
  const [playlistId, setPlaylistId] = useState(initial.playlistId);
  const [worksheets, setWorksheets] = useState([]);
  const [worksheetName, setWorksheetName] = useState(initial.worksheetName);
  const [columns, setColumns] = useState([]);
  const [titleColumn, setTitleColumn] = useState(initial.titleColumn);
  const [descriptionColumn, setDescriptionColumn] = useState(initial.descriptionColumn);
  const [selectedTeam, setSelectedTeam] = useState(initial.selectedTeam);
  const [teams, setTeams] = useState([]);
  const [teamPeople, setTeamPeople] = useState([]);
  const [enabledPeople, setEnabledPeople] = useState(initial.enabledPeople);
  const [randomPreview, setRandomPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [videos, setVideos] = useState([]);
  const [assignments, setAssignments] = useState({});
  const [selectedVideoIds, setSelectedVideoIds] = useState([]);
  const [bulkPerson, setBulkPerson] = useState('');
  const [playlistSource, setPlaylistSource] = useState('');
  const [playlistFallbackReason, setPlaylistFallbackReason] = useState('');
  const [loadingSheet, setLoadingSheet] = useState(false);
  const [loadingVideos, setLoadingVideos] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [configSaveError, setConfigSaveError] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [previewImage, setPreviewImage] = useState(null);
  const [taskBusyId, setTaskBusyId] = useState(null);
  const [quotaRefreshKey, setQuotaRefreshKey] = useState(0);
  const [hydrated, setHydrated] = useState(false);

  const applyConfig = (config) => {
    setSpreadsheetId(config.spreadsheetId);
    setPlaylistId(config.playlistId);
    setWorksheetName(config.worksheetName);
    setTitleColumn(config.titleColumn);
    setDescriptionColumn(config.descriptionColumn);
    setSelectedTeam(config.selectedTeam);
    setEnabledPeople(config.enabledPeople);
  };

  useEffect(() => {
    let cancelled = false;
    const cached = normalizeConfig(readRemembered(videoType), defaults, sysSettings);
    setHydrated(false);
    setWorksheets([]);
    setColumns([]);
    setTeams([]);
    setTeamPeople([]);
    setRandomPreview(null);
    setPreviewError('');
    setVideos([]);
    setAssignments({});
    setSelectedVideoIds([]);
    setBulkPerson('');
    applyConfig(cached);

    if (!authUser) {
      setHydrated(true);
      return () => { cancelled = true; };
    }

    api.getYoutubeDraftSettings()
      .then((data) => {
        if (cancelled) return;
        const serverConfig = data?.[videoType.toLowerCase()];
        applyConfig(normalizeConfig(serverConfig || cached, defaults, sysSettings));
      })
      .catch((err) => console.error('Failed to load YouTube draft settings:', err))
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });

    return () => { cancelled = true; };
  }, [videoType, authUser, sysSettings.default_spreadsheet_id, sysSettings.default_playlist_id]);

  useEffect(() => {
    if (!hydrated) return undefined;
    const cache = { spreadsheetId, playlistId, worksheetName, titleColumn, descriptionColumn, selectedTeam, enabledPeople };
    localStorage.setItem(storageKey(videoType), JSON.stringify(cache));
    if (!authUser) return undefined;

    const timer = window.setTimeout(() => {
      setConfigSaveError('');
      api.updateYoutubeDraftSettings(videoType, {
        spreadsheet_id: spreadsheetId,
        playlist_id: playlistId,
        worksheet_name: worksheetName,
        title_column: titleColumn,
        description_column: descriptionColumn,
        team: selectedTeam,
        enabled_people: enabledPeople,
      }).catch((err) => setConfigSaveError(`設定未能同步至伺服器：${err.message}`));
    }, 500);

    return () => window.clearTimeout(timer);
  }, [hydrated, authUser, videoType, spreadsheetId, playlistId, worksheetName, titleColumn, descriptionColumn, selectedTeam, enabledPeople]);

  useEffect(() => {
    const selectedWorksheet = worksheets.find((sheet) => sheet.title === worksheetName);
    const nextColumns = selectedWorksheet?.columns || [];
    setColumns(nextColumns);
    if (nextColumns.length && !nextColumns.includes(titleColumn)) {
      setTitleColumn(nextColumns.includes(defaults.title) ? defaults.title : nextColumns[0]);
    }
    if (nextColumns.length && !nextColumns.includes(descriptionColumn)) {
      setDescriptionColumn(nextColumns.includes(defaults.description) ? defaults.description : nextColumns[0]);
    }
  }, [worksheets, worksheetName]);

  useEffect(() => {
    if (!selectedTeam || !worksheetName || !spreadsheetId || !authUser) {
      setTeamPeople([]);
      return undefined;
    }
    let cancelled = false;
    api.getTeamPeople(spreadsheetId, worksheetName, selectedTeam)
      .then((res) => {
        if (cancelled) return;
        const people = res.people || [];
        setTeamPeople(people);
        setEnabledPeople((current) => current.filter((person) => people.includes(person)));
      })
      .catch((err) => {
        if (!cancelled) setErrorMsg(`讀取人物失敗：${err.message}`);
      });
    return () => { cancelled = true; };
  }, [selectedTeam, worksheetName, spreadsheetId, authUser]);

  const availablePeople = useMemo(
    () => teamPeople.filter((person) => enabledPeople.includes(person)),
    [teamPeople, enabledPeople],
  );

  useEffect(() => {
    if (bulkPerson && bulkPerson !== '不編輯' && !availablePeople.includes(bulkPerson)) setBulkPerson('');
  }, [availablePeople, bulkPerson]);

  const loadRandomPreview = async () => {
    if (!spreadsheetId || !worksheetName || !selectedTeam || !titleColumn || !descriptionColumn) {
      setRandomPreview(null);
      setPreviewError('請先選擇工作表、團體、標題欄位與描述欄位');
      return;
    }
    setLoadingPreview(true);
    setPreviewError('');
    try {
      const preview = await api.getRandomMemberPreview(
        spreadsheetId,
        worksheetName,
        selectedTeam,
        [titleColumn, descriptionColumn],
      );
      setRandomPreview(preview);
    } catch (err) {
      setRandomPreview(null);
      setPreviewError(err.message);
    } finally {
      setLoadingPreview(false);
    }
  };

  useEffect(() => {
    if (!hydrated || !authUser || !spreadsheetId || !worksheetName || !selectedTeam || !titleColumn || !descriptionColumn) {
      setRandomPreview(null);
      setPreviewError('');
      return;
    }
    loadRandomPreview();
  }, [hydrated, authUser, spreadsheetId, worksheetName, selectedTeam, titleColumn, descriptionColumn]);

  const loadSheetResources = async ({ showToast = false } = {}) => {
    if (!spreadsheetId) {
      if (showToast) toast.warning('請先填寫主要試算表 ID / URL');
      return;
    }
    setLoadingSheet(true);
    setErrorMsg(null);
    try {
      const metadata = await api.getSpreadsheetMetadata(spreadsheetId);
      const sheetList = metadata.worksheets || [];
      setWorksheets(sheetList);
      const nextWorksheet = sheetList.some((sheet) => sheet.title === worksheetName)
        ? worksheetName
        : sheetList.some((sheet) => sheet.title === defaults.worksheet)
          ? defaults.worksheet
          : sheetList[0]?.title || '';
      setWorksheetName(nextWorksheet);
      if (nextWorksheet) {
        const options = await api.parseSheetOptions(spreadsheetId, nextWorksheet);
        const nextTeams = options.teams || [];
        setTeams(nextTeams);
        setSelectedTeam((current) => nextTeams.includes(current) ? current : (nextTeams[0] || ''));
      } else {
        setTeams([]);
        setSelectedTeam('');
      }
      if (showToast) toast.success('工作表與欄位已刷新');
    } catch (err) {
      setErrorMsg(`刷新試算表失敗：${err.message}`);
    } finally {
      setLoadingSheet(false);
    }
  };

  useEffect(() => {
    if (hydrated && authUser && spreadsheetId) loadSheetResources();
  }, [hydrated, videoType]);

  const handleWorksheetChange = async (nextWorksheet) => {
    setWorksheetName(nextWorksheet);
    setTeams([]);
    setSelectedTeam('');
    setTeamPeople([]);
    setEnabledPeople([]);
    setRandomPreview(null);
    setPreviewError('');
    setSelectedVideoIds([]);
    setBulkPerson('');
    if (!nextWorksheet) return;
    try {
      const options = await api.parseSheetOptions(spreadsheetId, nextWorksheet);
      const nextTeams = options.teams || [];
      setTeams(nextTeams);
      setSelectedTeam(nextTeams[0] || '');
    } catch (err) {
      setErrorMsg(`讀取工作表選項失敗：${err.message}`);
    }
  };

  const handleLoadVideos = async () => {
    setLoadingVideos(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      const videoList = sortVideosByUploadTime(res.videos || []);
      setVideos(videoList);
      setAssignments(Object.fromEntries(videoList.map((video) => [video.video_id, '不編輯'])));
      setSelectedVideoIds([]);
      setBulkPerson('');
      setPlaylistSource(res.source || '');
      setPlaylistFallbackReason(res.fallback_reason || '');
      setQuotaRefreshKey((key) => key + 1);
    } catch (err) {
      setErrorMsg(`載入草稿影片失敗：${err.message}`);
    } finally {
      setLoadingVideos(false);
    }
  };

  const togglePerson = (person) => setEnabledPeople((current) => current.includes(person)
    ? current.filter((item) => item !== person)
    : [...current, person]);
  const setAllPeople = (checked) => setEnabledPeople(checked ? [...teamPeople] : []);
  const toggleVideoSelection = (videoId) => setSelectedVideoIds((current) => current.includes(videoId)
    ? current.filter((item) => item !== videoId)
    : [...current, videoId]);
  const setAllVideosSelected = (checked) => setSelectedVideoIds(checked ? videos.map((video) => video.video_id) : []);

  const applyBulkAssignment = () => {
    if (!selectedVideoIds.length) return toast.warning('請先勾選要批量編輯的影片');
    if (!bulkPerson) return toast.warning('請先選擇要套用的人物');
    const selectedCount = selectedVideoIds.length;
    setAssignments((current) => {
      const next = { ...current };
      selectedVideoIds.forEach((videoId) => { next[videoId] = bulkPerson; });
      return next;
    });
    setSelectedVideoIds([]);
    setBulkPerson('');
    toast.success(`已套用到 ${selectedCount} 支影片，尚未送出`);
  };

  const doExecute = async () => {
    setConfirmOpen(false);
    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.batchUpdateMetadata({
        spreadsheetUrlOrId: spreadsheetId,
        playlistId,
        videoType,
        worksheetName,
        titleColumn,
        descriptionColumn,
        team: selectedTeam,
        assignments: videos.map((video) => ({ video_id: video.video_id, person: assignments[video.video_id] || '不編輯' })),
      });
      setResult(res);
      await refresh({ background: true });
      setQuotaRefreshKey((key) => key + 1);
      toast.success(`已建立 ${res.total_count || res.task_ids?.length || 0} 筆影片任務，其中 ${res.skipped_count || 0} 筆略過。`);
    } catch (err) {
      setErrorMsg(`批次更新執行失敗：${err.message}`);
      toast.error('批次更新執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const requestExecute = () => {
    if (!worksheetName) return toast.warning('請先選擇工作表');
    if (!titleColumn || !descriptionColumn) return toast.warning('請先選擇標題與描述欄位');
    if (titleColumn === descriptionColumn) return toast.warning('標題與描述不能使用同一欄位');
    if (!selectedTeam) return toast.warning('請先選擇所屬團體');
    if (!videos.length) return toast.warning('請先讀取草稿影片');
    setConfirmOpen(true);
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

  return (
    <div className="section-gap">
      <ConfirmDialog open={confirmOpen} title={`確認更新 ${videoType}`} message={`將依「${worksheetName}」的「${titleColumn}」與「${descriptionColumn}」處理 ${videos.length} 支影片。未指定人物的影片會略過。`} confirmText="確認開始覆寫" cancelText="取消" variant="destructive" onConfirm={doExecute} onCancel={() => setConfirmOpen(false)} />
      <YouTubeQuotaBanner refreshKey={quotaRefreshKey} />

      <div>
        <div className="section-header"><VideoIcon size={24} color="var(--primary)" /><h1 style={{ fontSize: '1.8rem' }}>YouTube {videoType} 草稿</h1></div>
        <p className="section-desc">此頁只處理 {videoType}。先選工作表與欄位，再勾選要出現在人物下拉選單中的人物。</p>
      </div>

      <div className="top-filter-bar">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', borderBottom: '1px solid var(--border-color)', paddingBottom: 12 }}>
          <strong style={{ color: '#fff' }}><FileSpreadsheet size={17} style={{ verticalAlign: 'middle', marginRight: 7 }} />資料來源設定</strong>
          <button className="btn btn-primary" onClick={() => loadSheetResources({ showToast: true })} disabled={loadingSheet}><RefreshCw size={16} className={loadingSheet ? 'spin' : ''} /> {loadingSheet ? '刷新中...' : '刷新工作表與欄位'}</button>
        </div>
        <div className="top-filter-grid">
          <div className="form-group"><label className="form-label">主要試算表 ID / URL</label><SourceLinkInput value={spreadsheetId} onChange={(e) => setSpreadsheetId(e.target.value)} sourceType="spreadsheet" /></div>
          <div className="form-group"><label className="form-label">使用的工作表</label><select className="form-select" value={worksheetName} onChange={(e) => handleWorksheetChange(e.target.value)}>{worksheets.length ? worksheets.map((sheet) => <option key={sheet.title} value={sheet.title}>{sheet.title}</option>) : <option value={worksheetName}>{worksheetName || '請先刷新'}</option>}</select></div>
          <div className="form-group"><label className="form-label">標題套用欄位</label><select className="form-select" value={titleColumn} onChange={(e) => setTitleColumn(e.target.value)}>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></div>
          <div className="form-group"><label className="form-label">描述套用欄位</label><select className="form-select" value={descriptionColumn} onChange={(e) => setDescriptionColumn(e.target.value)}>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></div>
          <div className="form-group"><label className="form-label"><PlaySquare size={14} /> 目標播放清單 ID</label><SourceLinkInput value={playlistId} onChange={(e) => setPlaylistId(e.target.value)} sourceType="youtube-playlist" /></div>
        </div>
          <div className="info-banner"><Info size={14} color="var(--primary)" /><span>Video / Shorts 各自保存工作流設定；未指定的資源會使用全域共用 Google Sheet 或 YouTube 預設播放清單。設定以伺服器記憶為準，並同步保留於此瀏覽器的 localStorage 作快速快取。</span></div>
      </div>

      <div className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
        <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: 12 }}>
          <strong style={{ color: '#fff' }}><Users size={17} style={{ verticalAlign: 'middle', marginRight: 7 }} />團體與人物篩選</strong>
          <p className="section-desc" style={{ marginTop: 7 }}>先選團體，再勾選要出現在每支影片人物下拉選單中的人物；這個邏輯與 Instagram Reels 一致。</p>
        </div>
        <div className="form-group" style={{ maxWidth: 360 }}><label className="form-label">所屬團體</label><select className="form-select" value={selectedTeam} onChange={(e) => setSelectedTeam(e.target.value)} disabled={!teams.length}><option value="">{teams.length ? '請選擇團體' : '請先選擇工作表'}</option>{teams.map((team) => <option key={team} value={team}>{team}</option>)}</select></div>
        {teamPeople.length > 0 && <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
            <div><h2 style={{ fontSize: '1.1rem' }}>人物選項篩選（已啟用 {enabledPeople.length} / {teamPeople.length}）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 5 }}>只有勾選的人物會出現在下方每支影片的選項中。</p></div>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={enabledPeople.length === teamPeople.length} onChange={(e) => setAllPeople(e.target.checked)} /> 全選 / 全不選</label>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>{teamPeople.map((person) => <label key={person} className="glass-panel" style={{ padding: 12, display: 'flex', gap: 9, alignItems: 'center', cursor: 'pointer', borderColor: enabledPeople.includes(person) ? 'var(--primary)' : undefined }}><input type="checkbox" checked={enabledPeople.includes(person)} onChange={() => togglePerson(person)} /><span style={{ color: '#fff' }}>{person}</span></label>)}</div>
        </div>}
        {selectedTeam && !teamPeople.length && !errorMsg && <p className="section-desc">正在讀取團體人物…</p>}
      </div>

      <div className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: 8 }}><Shuffle size={19} /> 試算表隨機抽查</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 5 }}>從「{selectedTeam || '尚未選擇隊伍'}」隨機抽一位真實成員，顯示目前選用欄位的內容；全隊列不會被抽中。</p>
          </div>
          <button className="btn btn-primary" onClick={loadRandomPreview} disabled={loadingPreview || !selectedTeam}><RefreshCw size={16} className={loadingPreview ? 'spin' : ''} /> {loadingPreview ? '抽查中...' : randomPreview ? '換一位成員' : '隨機抽查'}</button>
        </div>
        {previewError && <div className="error-alert" style={{ marginTop: 14 }}><AlertCircle size={18} /><span>{previewError}</span></div>}
        {randomPreview && (
          <div style={{ marginTop: 16 }}>
            <div style={{ color: '#fff', marginBottom: 12 }}><strong>抽中成員：{randomPreview.person}</strong></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
              <PreviewField label={`標題欄位：${titleColumn}`} value={randomPreview.values?.[titleColumn]} />
              <PreviewField label={`描述欄位：${descriptionColumn}`} value={randomPreview.values?.[descriptionColumn]} />
            </div>
          </div>
        )}
      </div>

      {errorMsg && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{errorMsg}</span></div>}
      {configSaveError && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{configSaveError}；此瀏覽器快取仍已保留。</span></div>}

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button className="btn btn-primary" onClick={handleLoadVideos} disabled={loadingVideos}><RefreshCw size={16} className={loadingVideos ? 'spin' : ''} /> {loadingVideos ? '載入中...' : `讀取 ${videoType} 草稿影片`}</button></div>

      {videos.length > 0 && (
        <div className="section-gap" style={{ gap: 18 }}>
          <div><h2 style={{ fontSize: '1.3rem' }}>為每支影片指定人物（{videos.length} 支）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>來源：{sourceLabel}{playlistFallbackReason ? `；回退原因：${playlistFallbackReason}` : ''}</p></div>
          <div className="glass-panel bulk-edit-panel" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 14, flexWrap: 'wrap' }}>
              <div><h3 style={{ color: '#fff', fontSize: '1.05rem' }}>批量勾選編輯（已勾選 {selectedVideoIds.length} 支）</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>只會把人物選項套用到已勾選影片，不會送出或覆寫 YouTube。套用後會自動清除勾選。</p></div>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.length === videos.length} onChange={(e) => setAllVideosSelected(e.target.checked)} /> 全選 / 全不選</label>
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 14 }}>
              <div className="form-group" style={{ flex: '1 1 240px' }}><label className="form-label">批量套用人物</label><select className="form-select" value={bulkPerson} onChange={(e) => setBulkPerson(e.target.value)}><option value="">請選擇人物</option><option value="不編輯">不編輯（略過）</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
              <button className="btn btn-primary" onClick={applyBulkAssignment} disabled={!selectedVideoIds.length || !bulkPerson}>套用到已勾選影片</button>
            </div>
          </div>

          <div className="video-card-grid">{videos.map((video) => (
            <div key={video.video_id} className={`glass-panel video-card ${assignments[video.video_id] && assignments[video.video_id] !== '不編輯' ? 'video-card-assigned' : 'video-card-skipped'}`} style={{ borderColor: selectedVideoIds.includes(video.video_id) ? 'var(--primary)' : undefined }}>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.includes(video.video_id)} onChange={() => toggleVideoSelection(video.video_id)} /> 加入批量編輯</label>
              <div className="video-thumbnail-wrapper">{video.thumbnail_url ? <img className="video-thumbnail" src={video.thumbnail_url} alt={video.title} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.title })} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setPreviewImage({ src: video.thumbnail_url, alt: video.title }); }} role="button" tabIndex={0} /> : <div>無縮圖</div>}</div>
              <div><h4 style={{ color: '#fff', fontSize: '0.95rem' }}>{video.title || '無標題影片'}</h4><p style={{ color: 'var(--text-dim)', fontSize: '0.76rem' }}>Video ID: {video.video_id}</p></div>
              <div className="form-group" style={{ marginTop: 'auto' }}><label className="form-label">指定套用人物</label><select className="form-select" value={assignments[video.video_id] || '不編輯'} onChange={(e) => setAssignments((current) => ({ ...current, [video.video_id]: e.target.value }))}><option value="不編輯">不編輯（略過）</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
            </div>
          ))}</div>
          <div className="glass-panel execution-bar"><div><strong style={{ color: '#fff' }}>將處理目前清單中的 {videos.length} 支影片</strong><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>人物為「不編輯」的影片會安全略過。</p></div><button className="btn btn-success" onClick={requestExecute} disabled={executing}><Send size={18} /> {executing ? '批次更新中...' : '確認並開始覆寫'}</button></div>
        </div>
      )}

      {result && <div className="glass-panel" style={{ padding: 24, display: 'grid', gap: 12 }}><h3 style={{ color: '#34d399', display: 'flex', gap: 8, alignItems: 'center' }}><CheckCircle2 size={22} /> 已建立影片任務</h3><p style={{ color: 'var(--text-muted)' }}>批次 ID：{result.batch_id} · 已建立 {result.total_count || result.task_ids?.length || 0} 筆，略過 {result.skipped_count || 0} 筆。</p><div><button className="btn btn-secondary" type="button" onClick={() => setActiveTab?.('task_queue')}>到任務隊列查看</button></div>{resultTasks.map((task) => <TaskDetail key={task.id} task={task} compact busy={taskBusyId === task.id} onCancel={() => runTaskAction(cancelTask, task.id)} onRetry={() => runTaskAction(retryTask, task.id)} />)}</div>}
      <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}

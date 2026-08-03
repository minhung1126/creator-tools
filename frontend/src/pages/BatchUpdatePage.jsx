import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import { readPersistentJson, writePersistentJson } from '../utils/persistentStorage';
import ConfirmDialog from '../components/ConfirmDialog';
import ThumbnailDialog from '../components/ThumbnailDialog';
import SheetDataSourcePanel from '../components/SheetDataSourcePanel';
import SourceLinkInput from '../components/SourceLinkInput';
import TeamPersonFilterPanel from '../components/TeamPersonFilterPanel';
import useTeamPersonFilter from '../hooks/useTeamPersonFilter';
import { sortVideosByUploadTime } from '../utils/videoOrder';
import {
  AlertCircle,
  CheckCircle2,
  Info,
  PlaySquare,
  RefreshCw,
  Send,
  Shuffle,
  Video as VideoIcon,
} from 'lucide-react';

const DEFAULT_COLUMNS = {
  Video: { title: 'Youtube Title', description: 'Youtube Description', worksheet: 'Youtube Video' },
  Shorts: { title: 'Shorts Title', description: 'Shorts Description', worksheet: 'Youtube Shorts' },
};

const storageKey = (videoType) => `youtube-draft-config-${videoType.toLowerCase()}`;

function readRemembered(videoType) {
  return readPersistentJson(storageKey(videoType), {});
}

export function resolveDraftConfig(serverConfig, cached) {
  const hasServerConfig = serverConfig
    && typeof serverConfig === 'object'
    && !Array.isArray(serverConfig)
    && Object.keys(serverConfig).length > 0;
  return hasServerConfig ? serverConfig : cached;
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

export default function BatchUpdatePage({ sysSettings, authUser, videoType = 'Video' }) {
  const toast = useToast();
  const youtubeConnected = Boolean(authUser?.youtube_authenticated || authUser?.youtube?.authenticated);
  const defaults = DEFAULT_COLUMNS[videoType];
  const remembered = useMemo(() => readRemembered(videoType), [videoType]);
  const persistedDefaults = useMemo(() => ({
    default_spreadsheet_id: sysSettings.default_spreadsheet_id,
    default_playlist_id: sysSettings.default_playlist_id,
  }), [sysSettings.default_playlist_id, sysSettings.default_spreadsheet_id]);
  const initial = normalizeConfig(remembered, defaults, persistedDefaults);
  const [spreadsheetId, setSpreadsheetId] = useState(initial.spreadsheetId);
  const [appliedSpreadsheetId, setAppliedSpreadsheetId] = useState(initial.spreadsheetId);
  const [sourceReady, setSourceReady] = useState(false);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [playlistId, setPlaylistId] = useState(initial.playlistId);
  const [worksheets, setWorksheets] = useState([]);
  const [worksheetName, setWorksheetName] = useState(initial.worksheetName);
  const [columns, setColumns] = useState([]);
  const [titleColumn, setTitleColumn] = useState(initial.titleColumn);
  const [descriptionColumn, setDescriptionColumn] = useState(initial.descriptionColumn);
  const [randomPreview, setRandomPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [videos, setVideos] = useState([]);
  const [assignments, setAssignments] = useState(() => (
    remembered.assignments && typeof remembered.assignments === 'object' ? remembered.assignments : {}
  ));
  const [selectedVideoIds, setSelectedVideoIds] = useState(() => (
    Array.isArray(remembered.selectedVideoIds) ? remembered.selectedVideoIds : []
  ));
  const [bulkPerson, setBulkPerson] = useState(remembered.bulkPerson || '');
  const [playlistSource, setPlaylistSource] = useState('');
  const [playlistFallbackReason, setPlaylistFallbackReason] = useState('');
  const [loadingSheet, setLoadingSheet] = useState(false);
  const [loadingVideos, setLoadingVideos] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [configSaveError, setConfigSaveError] = useState('');
  const [sourceError, setSourceError] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [previewImage, setPreviewImage] = useState(null);
  const [quotaEstimate, setQuotaEstimate] = useState(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const initialLoadRequestedRef = useRef(false);
  const restoreVideoOptionsRef = useRef(true);

  const sourceStale = spreadsheetId.trim() !== appliedSpreadsheetId.trim();
  const teamPersonFilter = useTeamPersonFilter({
    source: appliedSpreadsheetId,
    worksheetName,
    enabled: Boolean(authUser && hydrated && sourceReady),
    initialTeam: initial.selectedTeam,
    initialSelectedPeople: initial.enabledPeople,
    defaultTeam: 'first',
    refreshKey: sourceRevision,
  });
  const {
    teams,
    selectedTeam,
    setSelectedTeam,
    people: teamPeople,
    selectedPeople: enabledPeople,
    setSelectedPeople: setEnabledPeople,
    loadingTeams,
    loadingPeople,
    ready: teamPersonReady,
    error: teamPeopleError,
    resetSelection,
  } = teamPersonFilter;
  const visibleSelectedTeam = sourceStale ? '' : selectedTeam;

  const applyConfig = useCallback((config) => {
    setSpreadsheetId(config.spreadsheetId);
    setAppliedSpreadsheetId(config.spreadsheetId);
    setSourceReady(false);
    setPlaylistId(config.playlistId);
    setWorksheetName(config.worksheetName);
    setTitleColumn(config.titleColumn);
    setDescriptionColumn(config.descriptionColumn);
    resetSelection({ team: config.selectedTeam, selectedPeople: config.enabledPeople });
  }, [resetSelection]);

  useEffect(() => {
    let cancelled = false;
    const cached = normalizeConfig(remembered, defaults, persistedDefaults);
    setHydrated(false);
    setWorksheets([]);
    setColumns([]);
    setSourceReady(false);
    setSourceError('');
    setRandomPreview(null);
    setPreviewError('');
    setVideos([]);
    setAssignments(remembered.assignments && typeof remembered.assignments === 'object' ? remembered.assignments : {});
    setSelectedVideoIds(Array.isArray(remembered.selectedVideoIds) ? remembered.selectedVideoIds : []);
    setBulkPerson(remembered.bulkPerson || '');
    initialLoadRequestedRef.current = false;
    restoreVideoOptionsRef.current = true;
    applyConfig(cached);

    if (!authUser) {
      setHydrated(true);
      return () => { cancelled = true; };
    }

    api.getYoutubeDraftSettings()
      .then((data) => {
        if (cancelled) return;
        const serverConfig = data?.[videoType.toLowerCase()];
        applyConfig(normalizeConfig(resolveDraftConfig(serverConfig, cached), defaults, persistedDefaults));
      })
      .catch((err) => console.error('Failed to load YouTube draft settings:', err))
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });

    return () => { cancelled = true; };
  }, [videoType, authUser, defaults, remembered, persistedDefaults, applyConfig]);

  useEffect(() => {
    if (!hydrated) return undefined;
    const saved = readRemembered(videoType);
    const selectionsReady = sourceReady && (!worksheetName || (teamPersonReady && !loadingPeople));
    const cache = {
      ...saved,
      spreadsheetId,
      playlistId,
      worksheetName,
      titleColumn,
      descriptionColumn,
      selectedTeam: selectionsReady ? selectedTeam : (saved.selectedTeam ?? selectedTeam),
      enabledPeople: selectionsReady ? enabledPeople : (Array.isArray(saved.enabledPeople) ? saved.enabledPeople : enabledPeople),
      assignments,
      selectedVideoIds,
      bulkPerson,
    };
    writePersistentJson(storageKey(videoType), cache);
    return undefined;
  }, [assignments, bulkPerson, descriptionColumn, enabledPeople, hydrated, loadingPeople, playlistId, selectedTeam, selectedVideoIds, sourceReady, spreadsheetId, teamPersonReady, titleColumn, videoType, worksheetName]);

  useEffect(() => {
    if (!hydrated || !authUser || !sourceReady || (worksheetName && (!teamPersonReady || loadingPeople))) return undefined;
    const timer = window.setTimeout(() => {
      setConfigSaveError('');
      api.updateYoutubeDraftSettings(videoType, {
        spreadsheet_id: appliedSpreadsheetId,
        playlist_id: playlistId,
        worksheet_name: worksheetName,
        title_column: titleColumn,
        description_column: descriptionColumn,
        team: selectedTeam,
        enabled_people: enabledPeople,
      }).catch((err) => setConfigSaveError(`設定未能同步至伺服器：${err.message}`));
    }, 500);
    return () => window.clearTimeout(timer);
  }, [hydrated, authUser, loadingPeople, sourceReady, teamPersonReady, videoType, appliedSpreadsheetId, playlistId, worksheetName, titleColumn, descriptionColumn, selectedTeam, enabledPeople]);

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
  }, [worksheets, worksheetName, titleColumn, descriptionColumn, defaults.title, defaults.description]);

  const availablePeople = useMemo(() => sourceStale ? [] : teamPeople.filter((person) => enabledPeople.includes(person)), [sourceStale, teamPeople, enabledPeople]);

  useEffect(() => {
    if (!sourceStale && !loadingPeople && teamPersonReady && bulkPerson && bulkPerson !== '不編輯' && !availablePeople.includes(bulkPerson)) setBulkPerson('');
  }, [availablePeople, bulkPerson, loadingPeople, sourceStale, teamPersonReady]);

  useEffect(() => {
    if (sourceStale || loadingPeople || !teamPersonReady || !videos.length) return;
    setAssignments((current) => Object.fromEntries(Object.entries(current).map(([videoId, person]) => [
      videoId,
      person === '不編輯' || availablePeople.includes(person) ? person : '不編輯',
    ])));
  }, [availablePeople, loadingPeople, sourceStale, teamPersonReady, videos.length]);

  const loadRandomPreview = useCallback(async () => {
    if (!appliedSpreadsheetId || !sourceReady || sourceStale || !worksheetName || !selectedTeam || !titleColumn || !descriptionColumn) {
      setRandomPreview(null);
      setPreviewError('請先選擇工作表、團體、標題欄位與描述欄位');
      return;
    }
    setLoadingPreview(true);
    setPreviewError('');
    try {
      const preview = await api.getRandomMemberPreview(appliedSpreadsheetId, worksheetName, selectedTeam, [titleColumn, descriptionColumn]);
      setRandomPreview(preview);
    } catch (err) {
      setRandomPreview(null);
      setPreviewError(err.message);
    } finally {
      setLoadingPreview(false);
    }
  }, [appliedSpreadsheetId, sourceReady, sourceStale, worksheetName, selectedTeam, titleColumn, descriptionColumn]);

  useEffect(() => {
    if (!hydrated || !authUser || !appliedSpreadsheetId || !sourceReady || sourceStale || !worksheetName || !selectedTeam || !titleColumn || !descriptionColumn) {
      setRandomPreview(null);
      setPreviewError('');
      return;
    }
    loadRandomPreview();
  }, [hydrated, authUser, appliedSpreadsheetId, sourceReady, sourceStale, worksheetName, selectedTeam, titleColumn, descriptionColumn, loadRandomPreview]);

  const loadSheetResources = useCallback(async ({ showToast = false } = {}) => {
    const nextSource = spreadsheetId.trim();
    if (!nextSource) {
      if (showToast) toast.warning('請先填寫主要試算表 ID / URL');
      return;
    }
    const sourceChanged = nextSource !== appliedSpreadsheetId.trim();
    setLoadingSheet(true);
    setErrorMsg(null);
    setSourceError('');
    try {
      const metadata = await api.getSpreadsheetMetadata(nextSource);
      const sheetList = metadata.worksheets || [];
      setWorksheets(sheetList);
      const nextWorksheet = sheetList.some((sheet) => sheet.title === worksheetName)
        ? worksheetName
        : sheetList.some((sheet) => sheet.title === defaults.worksheet)
          ? defaults.worksheet
          : sheetList[0]?.title || '';
      const worksheetChanged = nextWorksheet !== worksheetName;
      if (sourceChanged || worksheetChanged) {
        setRandomPreview(null);
        setPreviewError('');
        setSelectedVideoIds([]);
        setBulkPerson('');
        setAssignments(Object.fromEntries(videos.map((video) => [video.video_id, '不編輯'])));
        restoreVideoOptionsRef.current = false;
      }
      setAppliedSpreadsheetId(nextSource);
      setWorksheetName(nextWorksheet);
      setSourceReady(true);
      setSourceRevision((current) => current + 1);
      if (showToast) toast.success('工作表與欄位已刷新');
    } catch (err) {
      setSourceError(`刷新試算表失敗：${err.message}`);
    } finally {
      setLoadingSheet(false);
    }
  }, [appliedSpreadsheetId, defaults.worksheet, spreadsheetId, toast, videos, worksheetName]);

  useEffect(() => {
    if (hydrated && authUser && appliedSpreadsheetId && !initialLoadRequestedRef.current) {
      initialLoadRequestedRef.current = true;
      loadSheetResources();
    }
  }, [hydrated, authUser, appliedSpreadsheetId, loadSheetResources]);

  const handleSpreadsheetChange = (event) => {
    const nextValue = event.target.value;
    setSpreadsheetId(nextValue);
    setSourceError('');
  };

  const handleWorksheetChange = (nextWorksheet) => {
    setWorksheetName(nextWorksheet);
    setSelectedTeam('');
    setEnabledPeople([]);
    setRandomPreview(null);
    setPreviewError('');
    setSelectedVideoIds([]);
    setBulkPerson('');
    setAssignments(Object.fromEntries(videos.map((video) => [video.video_id, '不編輯'])));
    restoreVideoOptionsRef.current = false;
  };

  const handleLoadVideos = async () => {
    if (!youtubeConnected) {
      toast.warning('請先在「YouTube 設定」連結 YouTube 頻道 Google 帳號！');
      return;
    }
    setLoadingVideos(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      const videoList = sortVideosByUploadTime(res.videos || []);
      const shouldRestore = restoreVideoOptionsRef.current;
      const rememberedAssignments = shouldRestore && assignments && typeof assignments === 'object' ? assignments : {};
      const nextAssignments = Object.fromEntries(videoList.map((video) => [
        video.video_id,
        shouldRestore ? (rememberedAssignments[video.video_id] || '不編輯') : '不編輯',
      ]));
      const videoIds = new Set(videoList.map((video) => video.video_id));
      setVideos(videoList);
      setAssignments(nextAssignments);
      setSelectedVideoIds(shouldRestore ? selectedVideoIds.filter((videoId) => videoIds.has(videoId)) : []);
      if (!shouldRestore) setBulkPerson('');
      restoreVideoOptionsRef.current = false;
      setPlaylistSource(res.source || '');
      setPlaylistFallbackReason(res.fallback_reason || '');
    } catch (err) {
      setErrorMsg(`載入草稿影片失敗：${err.message}`);
    } finally {
      setLoadingVideos(false);
    }
  };

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
    if (!youtubeConnected) {
      setConfirmOpen(false);
      toast.warning('請先連結 YouTube 頻道 Google 帳號！');
      return;
    }
    setConfirmOpen(false);
    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.batchUpdateMetadata({
        spreadsheetUrlOrId: appliedSpreadsheetId,
        videoType,
        worksheetName,
        titleColumn,
        descriptionColumn,
        team: selectedTeam,
        assignments: videos.map((video) => ({ video_id: video.video_id, person: assignments[video.video_id] || '不編輯' })),
      });
      setResult(res);
      const summary = `成功 ${res.succeeded_count || 0} 筆、略過 ${res.skipped_count || 0} 筆、失敗 ${res.failed_count || 0} 筆`;
      if (res.quota_blocked || res.not_attempted_count) toast.warning(`YouTube 更新部分完成：${summary}`);
      else if (res.failed_count) toast.warning(`YouTube 更新完成但有失敗項目：${summary}`);
      else toast.success(`YouTube 更新完成：${summary}`);
    } catch (err) {
      setErrorMsg(`批次更新執行失敗：${err.message}`);
      toast.error('批次更新執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const requestExecute = async () => {
    if (!sourceReady || sourceStale) return toast.warning('請先刷新資料來源，讓目前來源設定套用完成');
    if (!worksheetName) return toast.warning('請先選擇工作表');
    if (!titleColumn || !descriptionColumn) return toast.warning('請先選擇標題與描述欄位');
    if (titleColumn === descriptionColumn) return toast.warning('標題與描述不能使用同一欄位');
    if (!selectedTeam) return toast.warning('請先選擇所屬團體');
    if (!videos.length) return toast.warning('請先讀取草稿影片');
    const activeCount = videos.filter((video) => assignments[video.video_id] && assignments[video.video_id] !== '不編輯').length;
    if (!activeCount) return toast.warning('目前沒有指定人物的影片');
    setEstimateLoading(true);
    try {
      setQuotaEstimate(await api.estimateYoutubeQuota({ operation: 'youtube.metadata_update', itemCount: activeCount }));
    } catch (error) {
      setQuotaEstimate(null);
      toast.warning(`無法取得 quota 預估，仍可直接執行：${error.message}`);
    } finally {
      setEstimateLoading(false);
    }
    setConfirmOpen(true);
  };

  const sourceLabel = playlistSource === 'youtube-api' ? 'YouTube API' : '';
  return (
    <div className="section-gap">
      <ConfirmDialog open={confirmOpen} title={`確認更新 ${videoType}`} message={`將依「${worksheetName}」的「${titleColumn}」與「${descriptionColumn}」直接處理 ${videos.filter((video) => assignments[video.video_id] && assignments[video.video_id] !== '不編輯').length} 支影片。${quotaEstimate ? `最壞估算 ${Number(quotaEstimate.projected_units || 0).toLocaleString()} units；今日安全可用 ${Number(quotaEstimate.effective_available_units || 0).toLocaleString()} units。${quotaEstimate.can_complete_today ? '預計可完成。' : '若執行途中達配額上限，未執行項目需在官方重設後重新送出。'}` : '未指定人物的影片會略過。'} `} confirmText={estimateLoading ? '估算中…' : '確認開始覆寫'} cancelText="取消" variant="destructive" onConfirm={doExecute} onCancel={() => setConfirmOpen(false)} />
      <div>
        <div className="section-header"><VideoIcon size={24} color="var(--primary)" /><h1 style={{ fontSize: '1.8rem' }}>YouTube {videoType} 草稿</h1></div>
        <p className="section-desc">此頁只處理 {videoType}。先確認資料來源、工作表與欄位，再勾選要出現在人物下拉選單中的人物。</p>
        {!youtubeConnected && <div className="info-banner"><AlertCircle size={16} /><span>尚未連結 YouTube 頻道 Google 帳號；請先到「YouTube 設定」授權管理品牌帳號的 Google 帳號。</span></div>}
      </div>

      <SheetDataSourcePanel
        spreadsheetId={spreadsheetId}
        onSpreadsheetIdChange={handleSpreadsheetChange}
        worksheets={worksheets}
        worksheetName={worksheetName}
        onWorksheetChange={handleWorksheetChange}
        onRefresh={() => loadSheetResources({ showToast: true })}
        loading={loadingSheet}
        sourceReady={sourceReady}
        stale={sourceStale}
        error={sourceError}
      >
        <div className="form-group"><label className="form-label" htmlFor="batch-title-column">標題套用欄位</label><select id="batch-title-column" className="form-select" value={titleColumn} onChange={(e) => setTitleColumn(e.target.value)}>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></div>
        <div className="form-group"><label className="form-label" htmlFor="batch-description-column">描述套用欄位</label><select id="batch-description-column" className="form-select" value={descriptionColumn} onChange={(e) => setDescriptionColumn(e.target.value)}>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></div>
        <div className="form-group"><label className="form-label" htmlFor="batch-playlist-id"><PlaySquare size={14} /> 目標播放清單 ID</label><SourceLinkInput id="batch-playlist-id" value={playlistId} onChange={(e) => setPlaylistId(e.target.value)} sourceType="youtube-playlist" /></div>
        <div className="info-banner filter-panel-full-width"><Info size={14} color="var(--primary)" /><span>Video / Shorts 各自保存所有工作流選項；未指定的資源會使用全域共用 Google Sheet 或 YouTube 預設播放清單。變更會即時保留於此瀏覽器，並在條件穩定後同步至伺服器。</span></div>
      </SheetDataSourcePanel>

      <TeamPersonFilterPanel
        teams={sourceStale ? [] : teams}
        selectedTeam={sourceStale ? '' : selectedTeam}
        onTeamChange={setSelectedTeam}
        people={sourceStale ? [] : teamPeople}
        selectedPeople={sourceStale ? [] : enabledPeople}
        onSelectedPeopleChange={setEnabledPeople}
        loadingTeams={loadingTeams}
        loadingPeople={loadingPeople}
        error={teamPeopleError}
        disabled={!authUser || !hydrated || !sourceReady || sourceStale}
        teamEmptyLabel="請選擇團體"
        peopleDisabledMessage="請先選擇團體；選定後才能載入人物。"
        description="先選擇團體，再勾選要出現在每支影片人物選單中的人物。"
      />

      <div className="glass-panel card-padding" style={{ display: 'grid', gap: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div><h2 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: 8 }}><Shuffle size={19} /> 試算表隨機抽查</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 5 }}>從「{visibleSelectedTeam || '尚未選擇團體'}」隨機抽一位真實成員，顯示目前選用欄位的內容；全團體列不會被抽中。</p></div>
          <button className="btn btn-primary" onClick={loadRandomPreview} disabled={loadingPreview || !visibleSelectedTeam}><RefreshCw size={16} className={loadingPreview ? 'spin' : ''} /> {loadingPreview ? '抽查中...' : randomPreview ? '換一位成員' : '隨機抽查'}</button>
        </div>
        {previewError && <div className="error-alert" style={{ marginTop: 14 }}><AlertCircle size={18} /><span>{previewError}</span></div>}
        {randomPreview && <div style={{ marginTop: 16 }}><div style={{ color: '#fff', marginBottom: 12 }}><strong>抽中成員：{randomPreview.person}</strong></div><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}><PreviewField label={`標題欄位：${titleColumn}`} value={randomPreview.values?.[titleColumn]} /><PreviewField label={`描述欄位：${descriptionColumn}`} value={randomPreview.values?.[descriptionColumn]} /></div></div>}
      </div>

      {errorMsg && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{errorMsg}</span></div>}
      {configSaveError && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{configSaveError}；此瀏覽器快取仍已保留。</span></div>}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button className="btn btn-primary" onClick={handleLoadVideos} disabled={loadingVideos}><RefreshCw size={16} className={loadingVideos ? 'spin' : ''} /> {loadingVideos ? '載入中...' : `讀取 ${videoType} 草稿影片`}</button></div>

      {videos.length > 0 && <div className="section-gap" style={{ gap: 18 }}>
        <div><h2 style={{ fontSize: '1.3rem' }}>為每支影片指定人物（{videos.length} 支）</h2><p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>來源：{sourceLabel}{playlistFallbackReason ? `；回退原因：${playlistFallbackReason}` : ''}</p></div>
        <div className="glass-panel bulk-edit-panel" style={{ padding: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 14, flexWrap: 'wrap' }}><div><h3 style={{ color: '#fff', fontSize: '1.05rem' }}>批量勾選編輯（已勾選 {selectedVideoIds.length} 支）</h3><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>只會把人物選項套用到已勾選影片，不會送出或覆寫 YouTube。套用後會自動清除勾選。</p></div><label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.length === videos.length} onChange={(e) => setAllVideosSelected(e.target.checked)} /> 全選 / 全不選</label></div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 14 }}><div className="form-group" style={{ flex: '1 1 240px' }}><label className="form-label">批量套用人物</label><select className="form-select" value={bulkPerson} onChange={(e) => setBulkPerson(e.target.value)}><option value="">請選擇人物</option><option value="不編輯">不編輯（略過）</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div><button className="btn btn-primary" onClick={applyBulkAssignment} disabled={!selectedVideoIds.length || !bulkPerson}>套用到已勾選影片</button></div>
        </div>
        <div className="video-card-grid">{videos.map((video) => <div key={video.video_id} className={`glass-panel video-card ${assignments[video.video_id] && assignments[video.video_id] !== '不編輯' ? 'video-card-assigned' : 'video-card-skipped'}`} style={{ borderColor: selectedVideoIds.includes(video.video_id) ? 'var(--primary)' : undefined }}>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#fff', cursor: 'pointer' }}><input type="checkbox" checked={selectedVideoIds.includes(video.video_id)} onChange={() => toggleVideoSelection(video.video_id)} /> 加入批量編輯</label>
          <div className="video-thumbnail-wrapper">{video.thumbnail_url ? <img className="video-thumbnail" src={video.thumbnail_url} alt={video.title} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.title })} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setPreviewImage({ src: video.thumbnail_url, alt: video.title }); }} role="button" tabIndex={0} /> : <div>無縮圖</div>}</div>
          <div><h4 style={{ color: '#fff', fontSize: '0.95rem' }}>{video.title || '無標題影片'}</h4><p style={{ color: 'var(--text-dim)', fontSize: '0.76rem' }}>Video ID: {video.video_id}</p></div>
          <div className="form-group" style={{ marginTop: 'auto' }}><label className="form-label">指定套用人物</label><select className="form-select" value={assignments[video.video_id] || '不編輯'} onChange={(e) => setAssignments((current) => ({ ...current, [video.video_id]: e.target.value }))}><option value="不編輯">不編輯（略過）</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
        </div>)}</div>
        <div className="glass-panel execution-bar"><div><strong style={{ color: '#fff' }}>將處理目前清單中的 {videos.length} 支影片</strong><p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>人物為「不編輯」的影片會安全略過。</p></div><button className="btn btn-success" onClick={requestExecute} disabled={executing}><Send size={18} /> {executing ? '批次更新中...' : '確認並開始覆寫'}</button></div>
      </div>}

      {result && <div className="glass-panel" style={{ padding: 24, display: 'grid', gap: 12 }}><h3 style={{ color: result.completed ? '#34d399' : '#fbbf24', display: 'flex', gap: 8, alignItems: 'center' }}><CheckCircle2 size={22} /> {result.completed ? 'YouTube 更新已執行完成' : 'YouTube 更新部分完成'}</h3><p style={{ color: 'var(--text-muted)' }}>共 {result.total_count || 0} 筆：成功 {result.succeeded_count || 0}、略過 {result.skipped_count || 0}、失敗 {result.failed_count || 0}、未執行 {result.not_attempted_count || 0}。</p>{result.quota_blocked && <div className="info-banner"><Info size={15} /><span>已達 YouTube 配額上限；未執行項目請於官方重設後重新送出。</span></div>}{(result.results || []).map((item) => <div key={item.video_id} className="result-item" style={{ alignItems: 'flex-start' }}><div style={{ flex: 1, minWidth: 0 }}><strong style={{ color: '#fff' }}>{item.title || item.video_id}</strong><div style={{ color: 'var(--text-dim)', fontSize: '0.78rem', marginTop: 4 }}>ID: {item.video_id}{item.person ? ` · ${item.person}` : ''}</div>{item.reason && <div style={{ color: item.status === 'failed' ? '#f87171' : '#fbbf24', fontSize: '0.8rem', marginTop: 4 }}>{item.reason}</div>}</div><span className={`badge ${item.status === 'succeeded' ? 'badge-connected' : item.status === 'failed' ? 'badge-disconnected' : 'badge-warning'}`}>{item.status === 'succeeded' ? '成功' : item.status === 'failed' ? '失敗' : item.status === 'skipped' ? '略過' : '未執行'}</span></div>)}</div>}
      <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';
import { useToast } from '../components/Toast';
import useAccountWorkState from '../hooks/useAccountWorkState';
import ConfirmDialog from '../components/ConfirmDialog';
import ThumbnailDialog from '../components/ThumbnailDialog';
import SheetDataSourcePanel from '../components/SheetDataSourcePanel';
import SourceLinkInput from '../components/SourceLinkInput';
import TeamPersonFilterPanel from '../components/TeamPersonFilterPanel';
import useTeamPersonFilter from '../hooks/useTeamPersonFilter';
import useSharedTeamPersonFilterPersistence from '../hooks/useSharedTeamPersonFilterPersistence';
import { normalizeTeamPersonFilter, readSharedTeamPersonFilter } from '../utils/teamPersonFilterStorage';
import { sortVideosByUploadTime } from '../utils/videoOrder';
import { youtubeIsConnected, youtubePreferredUiSlot, youtubeRoutingReasonLabel } from '../utils/youtubeRouting';
import {
  AlertCircle,
  CheckCircle2,
  Info,
  PlaySquare,
  RefreshCw,
  Save,
  Send,
  Shuffle,
  Video as VideoIcon,
} from 'lucide-react';

const DEFAULT_COLUMNS = {
  Video: { title: 'Youtube Title', description: 'Youtube Description', worksheet: 'Youtube Video' },
  Shorts: { title: 'Shorts Title', description: 'Shorts Description', worksheet: 'Youtube Shorts' },
};

export function resolveDraftConfig(serverConfig, cached) {
  const hasServerConfig = serverConfig
    && typeof serverConfig === 'object'
    && !Array.isArray(serverConfig)
    && Object.keys(serverConfig).length > 0;
  return hasServerConfig ? serverConfig : cached;
}

const TEAM_OPTION_SUFFIX = '（全隊）';

function normalizeConfig(raw, defaults, sysSettings, sharedFilter) {
  const normalizedSharedFilter = sharedFilter?.exists ? normalizeTeamPersonFilter(sharedFilter) : null;
  return {
    spreadsheetId: raw?.spreadsheetId || raw?.spreadsheet_id || sysSettings.default_spreadsheet_id || '',
    playlistId: raw?.playlistId || raw?.playlist_id || sysSettings.default_playlist_id || '',
    worksheetName: raw?.worksheetName || raw?.worksheet_name || defaults.worksheet,
    titleColumn: raw?.titleColumn || raw?.title_column || defaults.title,
    descriptionColumn: raw?.descriptionColumn || raw?.description_column || defaults.description,
    selectedTeam: normalizedSharedFilter?.team || '',
    selectedPeople: normalizedSharedFilter?.selectedPeople || [],
  };
}

function sheetRowValue(row, columns, label) {
  const column = columns.find((item) => item.label === label || item.key === label);
  if (!column) return '';
  return row?.cells?.[column.index] ?? '';
}

export function buildBatchPreview({
  videos = [],
  sheetRows = [],
  sheetColumns = [],
  team = '',
  titleColumn = '',
  descriptionColumn = '',
  assignments = {},
}) {
  return videos.map((video) => {
    const person = assignments[video.video_id] || '不編輯';
    const base = {
      videoId: video.video_id,
      video,
      person,
      currentTitle: video.title || '',
      currentDescription: video.description || '',
      newTitle: '',
      newDescription: '',
      status: 'skipped',
      reason: '',
      willUpdate: false,
    };
    if (!person || person === '不編輯') return { ...base, reason: '未指定人物' };

    const matches = sheetRows.filter((row) => {
      if (String(row?.team || '').trim() !== String(team || '').trim()) return false;
      const rowPerson = String(row?.person || '').trim();
      return person.endsWith(TEAM_OPTION_SUFFIX)
        ? !rowPerson
        : rowPerson === person;
    });
    if (!matches.length) return { ...base, reason: `找不到團體 ${team} 的選項 ${person} 資料` };

    const values = matches.map((row) => ({
      title: String(sheetRowValue(row, sheetColumns, titleColumn) || '').trim(),
      description: String(sheetRowValue(row, sheetColumns, descriptionColumn) || ''),
    }));
    const distinct = new Set(values.map((value) => JSON.stringify(value)));
    if (distinct.size > 1) return { ...base, reason: `團體 ${team} 的選項 ${person} 有多筆且標題或描述內容不同` };
    const next = values[0];
    if (!next.title) return { ...base, newDescription: next.description, reason: `工作表的 ${titleColumn} 為空白` };
    return {
      ...base,
      newTitle: next.title,
      newDescription: next.description,
      status: 'ready',
      willUpdate: true,
    };
  });
}

export function createPreviewToken() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function buildPreviewSnapshot({
  previewToken,
  spreadsheetId,
  playlistId,
  playlistSource,
  youtubeSlot,
  videoType,
  worksheetName,
  titleColumn,
  descriptionColumn,
  team,
  plan,
}) {
  return {
    previewToken,
    spreadsheetId,
    playlistId,
    playlistSource,
    youtubeSlot,
    videoType,
    worksheetName,
    titleColumn,
    descriptionColumn,
    team,
    plan: plan.map((item) => ({
      videoId: item.videoId,
      currentTitle: item.currentTitle,
      currentDescription: item.currentDescription,
      newTitle: item.newTitle,
      newDescription: item.newDescription,
      person: item.person,
      status: item.status,
      reason: item.reason,
    })),
  };
}

function PreviewField({ label, value }) {
  const hasValue = value !== null && value !== undefined && String(value).trim() !== '';
  return (
    <div className="glass-panel preview-field">
      <div className="preview-field-label">{label}</div>
      <div className={hasValue ? 'preview-field-value' : 'preview-field-value preview-field-empty'}>
        {hasValue ? String(value) : '此欄位目前是空白，請記得編輯試算表'}
      </div>
    </div>
  );
}

function previewStatusLabel(item) {
  if (item?.willUpdate || item?.status === 'ready') return '將更新';
  return item?.reason || '略過';
}

export default function BatchUpdatePage({ sysSettings, authUser, videoType = 'Video' }) {
  const toast = useToast();
  const activeSlot = youtubePreferredUiSlot(authUser?.youtube);
  const youtubeConnected = youtubeIsConnected(authUser?.youtube);
  const authorizationKey = useMemo(() => {
    const youtube = authUser?.youtube || {};
    const slots = ['primary', 'secondary'].map((slot) => {
      const record = youtube.slots?.[slot] || {};
      return [
        slot,
        record.configured,
        record.authenticated,
        record.channel_id,
        record.client_fingerprint,
        record.token_status,
        record.token_expires_at,
        record.last_refreshed_at,
      ];
    });
    return JSON.stringify({
      activeSlot,
      routingMode: youtube.routing_mode || 'auto_primary',
      slots,
    });
  }, [activeSlot, authUser?.youtube]);
  const defaults = DEFAULT_COLUMNS[videoType];
  const draftStateKey = videoType === 'Shorts' ? 'youtube_draft_shorts' : 'youtube_draft_video';
  const { value: rememberedState, error: workStateError, save: saveWorkState } = useAccountWorkState(draftStateKey, {});
  const remembered = useMemo(
    () => (rememberedState && typeof rememberedState === 'object' ? rememberedState : {}),
    [rememberedState],
  );
  const sharedFilter = useMemo(
    () => readSharedTeamPersonFilter(sysSettings.shared_team_person_filter),
    [sysSettings.shared_team_person_filter],
  );
  const persistedDefaults = useMemo(() => ({
    default_spreadsheet_id: sysSettings.default_spreadsheet_id,
    default_playlist_id: sysSettings.default_playlist_id,
  }), [sysSettings.default_playlist_id, sysSettings.default_spreadsheet_id]);
  const initial = normalizeConfig({}, defaults, persistedDefaults, sharedFilter);
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
  const [configDirty, setConfigDirty] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configSaved, setConfigSaved] = useState(false);
  const [randomPreview, setRandomPreview] = useState(null);
  const [randomPreviewLoading, setRandomPreviewLoading] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [batchPreview, setBatchPreview] = useState(null);
  const [previewToken, setPreviewToken] = useState('');
  const [previewSnapshot, setPreviewSnapshot] = useState(null);
  const [previewFingerprint, setPreviewFingerprint] = useState('');
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
  const [youtubeRoutingInfo, setYoutubeRoutingInfo] = useState(null);
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
  const hydrationStartedRef = useRef('');
  const playlistRequestRef = useRef(0);
  const sheetRequestRef = useRef(0);
  const randomPreviewRequestRef = useRef(0);
  const previousAuthorizationKeyRef = useRef(authorizationKey);

  const sourceStale = spreadsheetId.trim() !== appliedSpreadsheetId.trim();
  const teamPersonFilter = useTeamPersonFilter({
    source: appliedSpreadsheetId,
    worksheetName,
    enabled: Boolean(authUser && hydrated && sourceReady),
    initialTeam: initial.selectedTeam,
    initialSelectedPeople: initial.selectedPeople,
    defaultTeam: 'first',
    refreshKey: sourceRevision,
  });
  const {
    teams,
    selectedTeam,
    setSelectedTeam,
    people: teamPeople,
    selectedPeople,
    setSelectedPeople,
    loadingTeams,
    loadingPeople,
    ready: teamPersonReady,
    error: teamPeopleError,
    resetSelection,
  } = teamPersonFilter;
  const visibleSelectedTeam = sourceStale ? '' : selectedTeam;
  const filterPersistenceReady = hydrated && sourceReady && (!worksheetName || (teamPersonReady && !loadingPeople));
  const currentPreviewFingerprint = useMemo(() => JSON.stringify({
    spreadsheetId: appliedSpreadsheetId,
    playlistId,
    playlistSource,
    authorizationKey,
    videoType,
    worksheetName,
    titleColumn,
    descriptionColumn,
    team: selectedTeam,
    videos: videos.map((video) => ({ video_id: video.video_id, title: video.title || '', description: video.description || '' })),
    assignments,
  }), [appliedSpreadsheetId, assignments, authorizationKey, descriptionColumn, playlistId, playlistSource, selectedTeam, titleColumn, videoType, videos, worksheetName]);

  const sharedFilterPersistence = useSharedTeamPersonFilterPersistence({
    team: selectedTeam,
    selectedPeople,
    ready: filterPersistenceReady,
    onError: setConfigSaveError,
  });

  const invalidateLoadedVideos = useCallback(() => {
    playlistRequestRef.current += 1;
    setVideos([]);
    setPlaylistSource('');
    setPlaylistFallbackReason('');
    setYoutubeRoutingInfo(null);
    setBatchPreview(null);
    setLoadingPreview(false);
    setPreviewToken('');
    setPreviewSnapshot(null);
    setPreviewFingerprint('');
    setConfirmOpen(false);
    setEstimateLoading(false);
    setResult(null);
    setErrorMsg(null);
    setSelectedVideoIds([]);
    setAssignments({});
    setBulkPerson('');
    restoreVideoOptionsRef.current = false;
  }, []);

  const markConfigDirty = useCallback(() => {
    setConfigDirty(true);
    setConfigSaved(false);
    setConfigSaveError('');
  }, []);

  const saveDraftConfig = useCallback(async () => {
    if (!authUser) return;
    setConfigSaving(true);
    setConfigSaveError('');
    try {
      await api.updateYoutubeDraftSettings(videoType, {
        spreadsheet_id: spreadsheetId.trim(),
        playlist_id: playlistId.trim(),
        worksheet_name: worksheetName,
        title_column: titleColumn,
        description_column: descriptionColumn,
      });
      setConfigDirty(false);
      setConfigSaved(true);
      toast.success('YouTube 草稿設定已儲存');
    } catch (error) {
      setConfigSaveError(`設定未能同步至伺服器：${error.message}`);
    } finally {
      setConfigSaving(false);
    }
  }, [authUser, descriptionColumn, playlistId, spreadsheetId, titleColumn, toast, videoType, worksheetName]);

  const applyConfig = useCallback((config) => {
    setSpreadsheetId(config.spreadsheetId);
    setAppliedSpreadsheetId(config.spreadsheetId);
    setSourceReady(false);
    setPlaylistId(config.playlistId);
    setWorksheetName(config.worksheetName);
    setTitleColumn(config.titleColumn);
    setDescriptionColumn(config.descriptionColumn);
    resetSelection({ team: config.selectedTeam, selectedPeople: config.selectedPeople });
  }, [resetSelection]);

  useEffect(() => {
    const accountKey = authUser?.sub || authUser?.email || '';
    const hydrationKey = `${accountKey}:${videoType}`;
    if (hydrationStartedRef.current === hydrationKey) return undefined;
    hydrationStartedRef.current = hydrationKey;
    let cancelled = false;
    const fallbackConfig = normalizeConfig({}, defaults, persistedDefaults, sharedFilter);
    setHydrated(false);
    setConfigDirty(false);
    setConfigSaved(false);
    setWorksheets([]);
    setColumns([]);
    setSourceReady(false);
    setSourceError('');
    setRandomPreview(null);
    setPreviewError('');
    setBatchPreview(null);
    setPreviewToken('');
    setPreviewSnapshot(null);
    setPreviewFingerprint('');
    setVideos([]);
    setAssignments(remembered.assignments && typeof remembered.assignments === 'object' ? remembered.assignments : {});
    setSelectedVideoIds(Array.isArray(remembered.selectedVideoIds) ? remembered.selectedVideoIds : []);
    setBulkPerson(remembered.bulkPerson || '');
    initialLoadRequestedRef.current = false;
    restoreVideoOptionsRef.current = true;
    applyConfig(fallbackConfig);

    if (!accountKey) {
      setHydrated(true);
      return () => { cancelled = true; };
    }

    api.getYoutubeDraftSettings()
      .then((data) => {
        if (cancelled) return;
        const serverConfig = data?.[videoType.toLowerCase()];
        applyConfig(normalizeConfig(resolveDraftConfig(serverConfig, fallbackConfig), defaults, persistedDefaults, sharedFilter));
      })
      .catch((err) => setConfigSaveError(`讀取 YouTube 草稿設定失敗：${err.message}`))
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });

    return () => { cancelled = true; };
  }, [applyConfig, authUser?.email, authUser?.sub, defaults, persistedDefaults, sharedFilter, videoType, remembered.assignments, remembered.bulkPerson, remembered.selectedVideoIds]);

  useEffect(() => {
    if (!hydrated) return undefined;
    const cache = {
      assignments,
      selectedVideoIds,
      bulkPerson,
    };
    saveWorkState(cache);
    return undefined;
  }, [assignments, bulkPerson, hydrated, saveWorkState, selectedVideoIds]);

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

  const availablePeople = useMemo(() => sourceStale ? [] : teamPeople.filter((person) => selectedPeople.includes(person)), [sourceStale, teamPeople, selectedPeople]);

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
      setRandomPreviewLoading(false);
      return;
    }
    const requestId = randomPreviewRequestRef.current + 1;
    randomPreviewRequestRef.current = requestId;
    setRandomPreviewLoading(true);
    setPreviewError('');
    try {
      const preview = await api.getRandomMemberPreview(appliedSpreadsheetId, worksheetName, selectedTeam, [titleColumn, descriptionColumn]);
      if (requestId !== randomPreviewRequestRef.current) return;
      setRandomPreview(preview);
    } catch (err) {
      if (requestId !== randomPreviewRequestRef.current) return;
      setRandomPreview(null);
      setPreviewError(err.message);
    } finally {
      if (requestId === randomPreviewRequestRef.current) setRandomPreviewLoading(false);
    }
  }, [appliedSpreadsheetId, sourceReady, sourceStale, worksheetName, selectedTeam, titleColumn, descriptionColumn]);

  useEffect(() => {
    if (!hydrated || !authUser || !appliedSpreadsheetId || !sourceReady || sourceStale || !worksheetName || !selectedTeam || !titleColumn || !descriptionColumn) {
      randomPreviewRequestRef.current += 1;
      setRandomPreview(null);
      setPreviewError('');
      setRandomPreviewLoading(false);
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
    const requestId = sheetRequestRef.current + 1;
    sheetRequestRef.current = requestId;
    const sourceChanged = nextSource !== appliedSpreadsheetId.trim();
    setLoadingSheet(true);
    setErrorMsg(null);
    setSourceError('');
    try {
      const metadata = await api.getSpreadsheetMetadata(nextSource);
      if (requestId !== sheetRequestRef.current) return;
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
        invalidateLoadedVideos();
        if (worksheetChanged) markConfigDirty();
      }
      setAppliedSpreadsheetId(nextSource);
      setWorksheetName(nextWorksheet);
      setSourceReady(true);
      setSourceRevision((current) => current + 1);
      if (showToast) toast.success('工作表與欄位已刷新');
    } catch (err) {
      if (requestId !== sheetRequestRef.current) return;
      invalidateLoadedVideos();
      setSourceError(`刷新試算表失敗：${err.message}`);
    } finally {
      if (requestId === sheetRequestRef.current) setLoadingSheet(false);
    }
  }, [appliedSpreadsheetId, defaults.worksheet, invalidateLoadedVideos, markConfigDirty, spreadsheetId, toast, worksheetName]);

  useEffect(() => {
    if (hydrated && authUser && appliedSpreadsheetId && !initialLoadRequestedRef.current) {
      initialLoadRequestedRef.current = true;
      loadSheetResources();
    }
  }, [hydrated, authUser, appliedSpreadsheetId, loadSheetResources]);

  const handleSpreadsheetChange = (event) => {
    const nextValue = event.target.value;
    sheetRequestRef.current += 1;
    setSpreadsheetId(nextValue);
    setLoadingSheet(false);
    markConfigDirty();
    if (nextValue.trim() !== appliedSpreadsheetId.trim()) invalidateLoadedVideos();
    setSourceError('');
  };

  const handleWorksheetChange = (nextWorksheet) => {
    sheetRequestRef.current += 1;
    setWorksheetName(nextWorksheet);
    markConfigDirty();
    setSelectedTeam('');
    setSelectedPeople([]);
    setRandomPreview(null);
    setPreviewError('');
    invalidateLoadedVideos();
  };

  const handlePlaylistChange = (event) => {
    const nextValue = event.target.value;
    setPlaylistId(nextValue);
    markConfigDirty();
    if (nextValue.trim() !== playlistId.trim()) invalidateLoadedVideos();
  };

  useEffect(() => {
    if (previousAuthorizationKeyRef.current === authorizationKey) return;
    previousAuthorizationKeyRef.current = authorizationKey;
    invalidateLoadedVideos();
  }, [authorizationKey, invalidateLoadedVideos]);

  useEffect(() => {
    if (!batchPreview || !previewFingerprint || previewFingerprint === currentPreviewFingerprint) return;
    setBatchPreview(null);
    setPreviewToken('');
    setPreviewSnapshot(null);
    setPreviewFingerprint('');
    setConfirmOpen(false);
  }, [batchPreview, currentPreviewFingerprint, previewFingerprint]);

  const handleLoadVideos = async () => {
    if (!youtubeConnected) {
      toast.warning('請先在「YouTube 設定」連結 YouTube 頻道 Google 帳號！');
      return;
    }
    const shouldRestore = restoreVideoOptionsRef.current;
    const rememberedAssignments = shouldRestore && assignments && typeof assignments === 'object' ? assignments : {};
    const rememberedSelectedVideoIds = shouldRestore ? selectedVideoIds : [];
    invalidateLoadedVideos();
    const requestId = playlistRequestRef.current;
    setLoadingVideos(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.getPlaylistVideos(playlistId);
      if (playlistRequestRef.current !== requestId) return;
      const videoList = sortVideosByUploadTime(res.videos || []);
      const nextAssignments = Object.fromEntries(videoList.map((video) => [
        video.video_id,
        shouldRestore ? (rememberedAssignments[video.video_id] || '不編輯') : '不編輯',
      ]));
      const videoIds = new Set(videoList.map((video) => video.video_id));
      setVideos(videoList);
      setAssignments(nextAssignments);
      setSelectedVideoIds(shouldRestore ? rememberedSelectedVideoIds.filter((videoId) => videoIds.has(videoId)) : []);
      if (!shouldRestore) setBulkPerson('');
      restoreVideoOptionsRef.current = false;
      setPlaylistSource(res.source || '');
      setPlaylistFallbackReason(res.fallback_reason || '');
      setYoutubeRoutingInfo({
        slot: res.youtube_slot || '',
        reason: res.youtube_slot_reason || '',
      });
    } catch (err) {
      if (playlistRequestRef.current !== requestId) return;
      invalidateLoadedVideos();
      setErrorMsg(`載入草稿影片失敗：${err.message}`);
    } finally {
      setLoadingVideos(false);
    }
  };

  const toggleVideoSelection = (videoId) => setSelectedVideoIds((current) => current.includes(videoId)
    ? current.filter((item) => item !== videoId)
    : [...current, videoId]);
  const handleVideoCardClick = (event, videoId) => {
    if (event.target?.closest?.('button, input, select, textarea, a, label')) return;
    toggleVideoSelection(videoId);
  };
  const handleVideoCardKeyDown = (event, videoId) => {
    if (event.target !== event.currentTarget || !['Enter', ' '].includes(event.key)) return;
    event.preventDefault();
    toggleVideoSelection(videoId);
  };
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

  const loadBatchPreview = useCallback(async () => {
    const requestVersion = playlistRequestRef.current;
    setLoadingPreview(true);
    setErrorMsg(null);
    try {
      const response = await api.getBatchPreview({
        spreadsheetUrlOrId: appliedSpreadsheetId,
        playlistId,
        videoType,
        worksheetName,
        titleColumn,
        descriptionColumn,
        team: selectedTeam,
        assignments: videos.map((video) => ({
          video_id: video.video_id,
          person: assignments[video.video_id] || '不編輯',
        })),
      });
      if (playlistRequestRef.current !== requestVersion) throw new Error('目前播放清單已變更，請重新讀取影片後再預覽。');
      const plan = Array.isArray(response?.plan) ? response.plan : [];
      const token = response?.preview_token || '';
      const snapshot = response?.preview_snapshot || null;
      if (!token || !snapshot) throw new Error('伺服器未提供可驗證的預覽，請重新整理後再試。');
      setBatchPreview(plan);
      setPreviewToken(token);
      setPreviewSnapshot(snapshot);
      setYoutubeRoutingInfo({
        slot: snapshot?.youtube_slot || response.youtube_slot || '',
        reason: snapshot?.youtube_slot_reason || response.youtube_slot_reason || '',
      });
      setPreviewFingerprint(currentPreviewFingerprint);
      return { plan, snapshot };
    } catch (error) {
      setBatchPreview(null);
      setPreviewToken('');
      setPreviewSnapshot(null);
      setPreviewFingerprint('');
      setErrorMsg(`建立完整批次預覽失敗：${error.message}`);
      return null;
    } finally {
      setLoadingPreview(false);
    }
  }, [appliedSpreadsheetId, assignments, currentPreviewFingerprint, descriptionColumn, playlistId, selectedTeam, titleColumn, videoType, videos, worksheetName]);

  const doExecute = async () => {
    if (!youtubeConnected) {
      setConfirmOpen(false);
      toast.warning('請先連結 YouTube 頻道 Google 帳號！');
      return;
    }
    if (!previewToken || !previewSnapshot || previewFingerprint !== currentPreviewFingerprint) {
      setConfirmOpen(false);
      setErrorMsg('完整批次預覽已過期，已安全停止；請重新產生預覽後再執行。');
      return;
    }
    setConfirmOpen(false);
    setExecuting(true);
    setErrorMsg(null);
    setResult(null);
    try {
      const res = await api.batchUpdateMetadata({
        spreadsheetUrlOrId: appliedSpreadsheetId,
        playlistId,
        videoType,
        worksheetName,
        titleColumn,
        descriptionColumn,
        team: selectedTeam,
        assignments: videos.map((video) => ({ video_id: video.video_id, person: assignments[video.video_id] || '不編輯' })),
        youtubeSlot: previewSnapshot?.youtube_slot,
        previewToken,
        previewSnapshot,
      });
      setResult(res);
      setBatchPreview(null);
      setPreviewToken('');
      setPreviewSnapshot(null);
      setPreviewFingerprint('');
      const summary = `成功 ${res.succeeded_count || 0} 筆、略過 ${res.skipped_count || 0} 筆、失敗 ${res.failed_count || 0} 筆`;
      if (res.quota_blocked || res.not_attempted_count) toast.warning(`YouTube 更新部分完成：${summary}`);
      else if (res.failed_count) toast.warning(`YouTube 更新完成但有失敗項目：${summary}`);
      else toast.success(`YouTube 更新完成：${summary}`);
    } catch (err) {
      if (err.code === 'stale_preview' || err.status === 409) {
        setResult(null);
        setBatchPreview(null);
        setPreviewToken('');
        setPreviewSnapshot(null);
        setPreviewFingerprint('');
        setErrorMsg('預覽已過期或資料已變更，已安全停止批次更新；請重新讀取影片並產生完整預覽。');
        toast.warning('預覽已過期，批次更新已安全停止');
        return;
      }
      setErrorMsg(`批次更新執行失敗：${err.message}`);
      toast.error('批次更新執行失敗');
    } finally {
      setExecuting(false);
    }
  };

  const requestExecute = async () => {
    if (executing || loadingPreview) return;
    if (!sourceReady || sourceStale) return toast.warning('請先刷新資料來源，讓目前來源設定套用完成');
    if (!worksheetName) return toast.warning('請先選擇工作表');
    if (!titleColumn || !descriptionColumn) return toast.warning('請先選擇標題與描述欄位');
    if (titleColumn === descriptionColumn) return toast.warning('標題與描述不能使用同一欄位');
    if (!selectedTeam) return toast.warning('請先選擇所屬團體');
    if (!videos.length) return toast.warning('請先讀取草稿影片');
    const previewResult = await loadBatchPreview();
    if (!previewResult) return;
    const { plan, snapshot } = previewResult;
    const activeCount = plan.filter((item) => item.willUpdate).length;
    if (!activeCount) return toast.warning('完整預覽中沒有可更新的影片');
    setEstimateLoading(true);
    try {
      setQuotaEstimate(await api.estimateYoutubeQuota({
        operation: 'youtube.metadata_update',
        itemCount: activeCount,
        slot: snapshot?.youtube_slot || activeSlot,
      }));
    } catch (error) {
      setQuotaEstimate(null);
      toast.warning(`無法取得 quota 預估，仍可直接執行：${error.message}`);
    } finally {
      setEstimateLoading(false);
    }
    setConfirmOpen(true);
  };

  const sourceLabel = playlistSource === 'youtube-api' ? 'YouTube API' : '';
  const previewUpdateCount = batchPreview?.filter((item) => item.willUpdate || item.status === 'ready').length || 0;
  const previewSkipCount = batchPreview ? batchPreview.length - previewUpdateCount : 0;
  return (
    <div className="section-gap batch-update-page">
      <ConfirmDialog open={confirmOpen} title={`確認更新 ${videoType}`} message={`完整預覽共 ${batchPreview?.length || 0} 支：將更新 ${previewUpdateCount} 支，略過 ${previewSkipCount} 支。${quotaEstimate ? `最壞估算 ${Number(quotaEstimate.projected_units || 0).toLocaleString()} 單位；今日安全可用 ${Number(quotaEstimate.effective_available_units || 0).toLocaleString()} 單位。${quotaEstimate.can_complete_today ? '預計可完成。' : '若執行途中達配額上限，未執行項目需在官方重設後重新送出。'}` : ''}`} confirmText={estimateLoading ? '估算中…' : '確認開始覆寫'} cancelText="取消" variant="destructive" busy={executing || estimateLoading} onConfirm={doExecute} onCancel={() => setConfirmOpen(false)} />
      <header className="page-header">
        <div className="section-header"><VideoIcon size={24} color="var(--primary)" /><h1>YouTube {videoType} 草稿</h1></div>
        <p className="section-desc">此頁只處理 {videoType}。先確認資料來源、工作表與欄位，再勾選要出現在人物下拉選單中的人物。</p>
        {youtubeRoutingInfo?.slot && <p className="section-desc">本次 YouTube routing：{youtubeRoutingInfo.slot}；{youtubeRoutingReasonLabel(youtubeRoutingInfo.reason)}</p>}
        {!youtubeConnected && <div className="info-banner"><AlertCircle size={16} /><span>尚未連結 YouTube 頻道 Google 帳號；請先到「YouTube 設定」授權管理品牌帳號的 Google 帳號。</span></div>}
      </header>

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
        <div className="info-banner filter-panel-full-width"><Info size={14} color="var(--primary)" /><span>Video / Shorts 各自保存工作表、欄位與工作流資源；Sheet 內容複製、Video、Shorts 共用目前帳號的團體與人物篩選。未指定的資源會使用目前帳號的預設 Google Sheet 或 YouTube 播放清單。</span></div>
      </SheetDataSourcePanel>

      <div className="glass-panel card-padding playlist-input-panel">
        <label className="form-label" htmlFor="batch-playlist-id"><PlaySquare size={14} /> 目標播放清單 ID 或網址</label>
        <SourceLinkInput id="batch-playlist-id" value={playlistId} onChange={handlePlaylistChange} sourceType="youtube-playlist" disabled={executing || loadingVideos} />
        <p className="section-desc">播放清單與試算表是獨立資料來源；切換播放清單後必須重新讀取影片。</p>
      </div>

      <TeamPersonFilterPanel
        teams={sourceStale ? [] : teams}
        selectedTeam={sourceStale ? '' : selectedTeam}
        onTeamChange={setSelectedTeam}
        people={sourceStale ? [] : teamPeople}
        selectedPeople={sourceStale ? [] : selectedPeople}
        onSelectedPeopleChange={setSelectedPeople}
        loadingTeams={loadingTeams}
        loadingPeople={loadingPeople}
        error={teamPeopleError}
        disabled={!authUser || !hydrated || !sourceReady || sourceStale}
        teamEmptyLabel="請選擇團體"
        peopleDisabledMessage="請先選擇團體；選定後才能載入人物。"
        description="先選擇團體，再勾選要出現在每支影片人物選單中的人物。"
      />

      <div className="glass-panel card-padding random-preview-panel card-stack">
        <div className="action-bar">
          <div><h2 className="panel-title"><Shuffle size={19} /> 試算表隨機抽查</h2><p className="panel-description">從「{visibleSelectedTeam || '尚未選擇團體'}」隨機抽一位真實成員，顯示目前選用欄位的內容；全團體列不會被抽中。</p></div>
          <div className="page-actions"><button className="btn btn-primary" onClick={loadRandomPreview} disabled={randomPreviewLoading || !visibleSelectedTeam}><RefreshCw size={16} className={randomPreviewLoading ? 'spin' : ''} /> {randomPreviewLoading ? '抽查中...' : randomPreview ? '換一位成員' : '隨機抽查'}</button></div>
        </div>
        {previewError && <div className="error-alert"><AlertCircle size={18} /><span>{previewError}</span></div>}
        {randomPreview && <div className="random-preview-content"><div className="random-preview-person"><strong>抽中成員：{randomPreview.person}</strong></div><div className="responsive-grid"><PreviewField label={`標題欄位：${titleColumn}`} value={randomPreview.values?.[titleColumn]} /><PreviewField label={`描述欄位：${descriptionColumn}`} value={randomPreview.values?.[descriptionColumn]} /></div></div>}
      </div>

      {errorMsg && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{errorMsg}</span></div>}
      {workStateError && <div className="filter-panel-status filter-panel-status-error" role="alert">工作狀態同步失敗：{workStateError}</div>}
      {configSaveError && <div className="glass-panel error-alert"><AlertCircle size={20} /><span>{configSaveError}</span></div>}
      <div className="page-actions"><button className="btn btn-primary" onClick={handleLoadVideos} disabled={loadingVideos}><RefreshCw size={16} className={loadingVideos ? 'spin' : ''} /> {loadingVideos ? '載入中...' : `讀取 ${videoType} 草稿影片`}</button></div>

      {videos.length > 0 && <div className="section-gap batch-videos">
        <div className="page-header"><h2>為每支影片指定人物（{videos.length} 支）</h2><p className="section-desc batch-source-label">來源：{sourceLabel}{playlistFallbackReason ? `；回退原因：${playlistFallbackReason}` : ''}</p></div>
        <div className="glass-panel bulk-edit-panel card-stack">
          <div className="action-bar bulk-edit-heading"><div><h3>批量勾選編輯（已勾選 {selectedVideoIds.length} 支）</h3><p>只會把人物選項套用到已勾選影片，不會送出或覆寫 YouTube。套用後會自動清除勾選。</p></div><label className="bulk-select-all"><input type="checkbox" checked={selectedVideoIds.length === videos.length} onChange={(e) => setAllVideosSelected(e.target.checked)} /> 全選 / 全不選</label></div>
          <div className="toolbar bulk-edit-controls"><div className="form-group bulk-person-field"><label className="form-label">批量套用人物</label><select className="form-select" value={bulkPerson} onChange={(e) => setBulkPerson(e.target.value)}><option value="">請選擇人物</option><option value="不編輯">不編輯（略過）</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div><button className="btn btn-primary" onClick={applyBulkAssignment} disabled={!selectedVideoIds.length || !bulkPerson}>套用到已勾選影片</button></div>
        </div>
        <div className="video-card-grid">{videos.map((video) => <div key={video.video_id} className={`glass-panel video-card ${assignments[video.video_id] && assignments[video.video_id] !== '不編輯' ? 'video-card-assigned' : 'video-card-skipped'}${selectedVideoIds.includes(video.video_id) ? ' video-card-selected' : ''}`} role="button" tabIndex={0} aria-pressed={selectedVideoIds.includes(video.video_id)} aria-label={`${selectedVideoIds.includes(video.video_id) ? '取消選取' : '選取'}${video.title || '影片'}加入批量編輯`} onClick={(event) => handleVideoCardClick(event, video.video_id)} onKeyDown={(event) => handleVideoCardKeyDown(event, video.video_id)}>
          <label className="video-select-label"><input type="checkbox" checked={selectedVideoIds.includes(video.video_id)} onChange={() => toggleVideoSelection(video.video_id)} /> 加入批量編輯</label>
          <div className="video-thumbnail-wrapper">{video.thumbnail_url ? <button type="button" className="video-thumbnail-button" aria-label={`放大檢視${video.title || '影片'}縮圖`} onClick={() => setPreviewImage({ src: video.thumbnail_url, alt: video.title })}><img className="video-thumbnail" src={video.thumbnail_url} alt="" /></button> : <div>無縮圖</div>}</div>
          <div className="video-card-copy"><h4>{video.title || '無標題影片'}</h4><p>Video ID: {video.video_id}</p></div>
          <div className="form-group video-card-assignment"><label className="form-label">指定套用人物</label><select className="form-select" value={assignments[video.video_id] || '不編輯'} onChange={(e) => setAssignments((current) => ({ ...current, [video.video_id]: e.target.value }))}><option value="不編輯">不編輯（略過）</option>{availablePeople.map((person) => <option key={person} value={person}>{person}</option>)}</select></div>
        </div>)}</div>
        {batchPreview && <section className="glass-panel card-padding batch-preview-panel" aria-label="完整批次變更預覽">
          <div className="page-header"><h3>完整批次變更預覽</h3><p className="section-desc">逐片核對目前值、新值、人物與略過原因；確認的是這份完整計畫。</p></div>
          <div className="batch-preview-list">
            {batchPreview.map((item) => (
              <article className={`batch-preview-item ${item.willUpdate || item.status === 'ready' ? 'batch-preview-item-ready' : 'batch-preview-item-skipped'}`} key={item.videoId || item.video_id}>
                <div className="batch-preview-item-heading"><strong>{item.currentTitle || item.videoId || item.video_id}</strong><span className="badge">{item.willUpdate || item.status === 'ready' ? '將更新' : '略過'}</span></div>
                <div className="batch-preview-item-meta">影片 ID：{item.videoId || item.video_id} · 人物：{item.person || '未指定'}</div>
                <div className="batch-preview-values"><div><span>目前標題</span><p>{item.currentTitle || '（空白）'}</p></div><div><span>新標題</span><p>{item.newTitle || '（不變更）'}</p></div><div><span>目前描述</span><p>{item.currentDescription || '（空白）'}</p></div><div><span>新描述</span><p>{item.newDescription || '（不變更）'}</p></div></div>
                {item.reason && <p className="batch-preview-reason">略過原因：{previewStatusLabel(item)}</p>}
              </article>
            ))}
          </div>
        </section>}
        <div className="glass-panel execution-bar"><div><strong>將處理目前清單中的 {videos.length} 支影片</strong><p>人物為「不編輯」的影片會安全略過。</p></div><button className="btn btn-success" onClick={requestExecute} disabled={executing}><Send size={18} /> {executing ? '批次更新中...' : '確認並開始覆寫'}</button></div>
      </div>}

      {result && <div className="glass-panel card-padding result-panel card-stack"><h3 className={result.completed ? 'result-heading result-heading-success' : 'result-heading result-heading-warning'}><CheckCircle2 size={22} /> {result.completed ? 'YouTube 更新已執行完成' : 'YouTube 更新部分完成'}</h3><p className="section-desc">共 {result.total_count || 0} 筆：成功 {result.succeeded_count || 0}、略過 {result.skipped_count || 0}、失敗 {result.failed_count || 0}、未執行 {result.not_attempted_count || 0}。</p>{result.quota_blocked && <div className="info-banner"><Info size={15} /><span>已達 YouTube 配額上限；未執行項目請於官方重設後重新送出。</span></div>}{(result.results || []).map((item) => <div key={item.video_id} className="result-item result-row"><div><strong>{item.title || item.video_id}</strong><div className="result-meta">ID: {item.video_id}{item.person ? ` · ${item.person}` : ''}</div>{item.reason && <div className={item.status === 'failed' ? 'result-reason result-reason-failed' : 'result-reason'}>{item.reason}</div>}</div><span className={`badge ${item.status === 'succeeded' ? 'badge-connected' : item.status === 'failed' ? 'badge-disconnected' : 'badge-warning'}`}>{item.status === 'succeeded' ? '成功' : item.status === 'failed' ? '失敗' : item.status === 'skipped' ? '略過' : '未執行'}</span></div>)}</div>}
      <ThumbnailDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Check, Clipboard, FileSpreadsheet, Search } from 'lucide-react';
import { api } from '../services/api';
import SheetDataSourcePanel from '../components/SheetDataSourcePanel';
import TeamPersonFilterPanel from '../components/TeamPersonFilterPanel';
import useTeamPersonFilter from '../hooks/useTeamPersonFilter';
import useSharedTeamPersonFilterPersistence from '../hooks/useSharedTeamPersonFilterPersistence';
import { readPersistentJson, writePersistentJson } from '../utils/persistentStorage';
import { readSharedTeamPersonFilter, stripTeamPersonFilter } from '../utils/teamPersonFilterStorage';

const STORAGE_KEY = 'creator-tools.sheet-copy.v1';

function loadSaved() {
  return readPersistentJson(STORAGE_KEY, {});
}

export function migrateSelectedPeople(saved) {
  return Array.isArray(saved?.selectedPeople) ? saved.selectedPeople : saved?.person ? [saved.person] : [];
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('瀏覽器拒絕存取剪貼簿');
}

export default function SheetCopyPage({ sysSettings }) {
  const saved = useMemo(loadSaved, []);
  const sharedFilter = useMemo(
    () => readSharedTeamPersonFilter(sysSettings.shared_team_person_filter),
    [sysSettings.shared_team_person_filter],
  );
  const initialSpreadsheetId = saved.spreadsheetId || sysSettings.default_spreadsheet_id || '';
  const [spreadsheetId, setSpreadsheetId] = useState(initialSpreadsheetId);
  const [appliedSpreadsheetId, setAppliedSpreadsheetId] = useState(initialSpreadsheetId);
  const [sourceReady, setSourceReady] = useState(false);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [worksheets, setWorksheets] = useState([]);
  const [worksheetName, setWorksheetName] = useState(saved.worksheetName || '');
  const [columns, setColumns] = useState([]);
  const [visibleKeys, setVisibleKeys] = useState(Array.isArray(saved.visibleKeys) ? saved.visibleKeys : []);
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState(saved.query || '');
  const [loading, setLoading] = useState(false);
  const [sourceError, setSourceError] = useState('');
  const [sharedFilterSaveError, setSharedFilterSaveError] = useState('');
  const [copiedCell, setCopiedCell] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  const initialLoadRequestedRef = useRef(false);
  const worksheetRequestRef = useRef(0);

  const sourceStale = spreadsheetId.trim() !== appliedSpreadsheetId.trim();
  const teamPersonFilter = useTeamPersonFilter({
    source: appliedSpreadsheetId,
    worksheetName,
    enabled: sourceReady,
    initialTeam: sharedFilter.exists ? sharedFilter.team : (saved.team || ''),
    initialSelectedPeople: sharedFilter.exists ? sharedFilter.selectedPeople : migrateSelectedPeople(saved),
    defaultTeam: 'none',
    refreshKey: sourceRevision,
  });
  const {
    teams,
    selectedTeam,
    setSelectedTeam,
    people,
    selectedPeople,
    setSelectedPeople,
    loadingTeams,
    loadingPeople,
    ready: teamPersonReady,
    error: teamPersonError,
  } = teamPersonFilter;

  const filterPersistenceReady = sourceReady && (!worksheetName || (teamPersonReady && !loadingPeople));

  useSharedTeamPersonFilterPersistence({
    team: selectedTeam,
    selectedPeople,
    ready: filterPersistenceReady,
    onError: setSharedFilterSaveError,
  });

  useEffect(() => {
    const savedState = loadSaved();
    writePersistentJson(STORAGE_KEY, {
      ...(filterPersistenceReady ? stripTeamPersonFilter(savedState) : savedState),
      spreadsheetId,
      worksheetName,
      visibleKeys,
      query,
    });
  }, [filterPersistenceReady, query, spreadsheetId, visibleKeys, worksheetName]);

  useEffect(() => {
    if (!copiedCell) return undefined;
    const timer = window.setTimeout(() => setCopiedCell(''), 1200);
    return () => window.clearTimeout(timer);
  }, [copiedCell]);

  const loadWorksheet = useCallback(async (name, source) => {
    if (!name || !source) return;
    const requestId = worksheetRequestRef.current + 1;
    worksheetRequestRef.current = requestId;
    setWorksheetName(name);
    setRows([]);
    setColumns([]);
    setSourceError('');
    try {
      const table = await api.getCopyableSheetTable(source, name);
      if (worksheetRequestRef.current !== requestId) return;
      const nextColumns = table.columns || [];
      const retained = visibleKeys.filter((key) => nextColumns.some((column) => column.key === key));
      setColumns(nextColumns);
      setVisibleKeys(retained.length ? retained : nextColumns.map((column) => column.key));
      setRows(table.rows || []);
    } catch (err) {
      if (worksheetRequestRef.current === requestId) setSourceError(`讀取工作表內容失敗：${err.message}`);
    }
  }, [visibleKeys]);

  const refresh = useCallback(async () => {
    const nextSource = spreadsheetId.trim();
    if (!nextSource) {
      setSourceError('請先輸入主要試算表 ID 或網址');
      return;
    }
    setLoading(true);
    setSourceError('');
    try {
      const metadata = await api.getSpreadsheetMetadata(nextSource);
      const nextWorksheets = metadata.worksheets || [];
      const nextName = nextWorksheets.some((sheet) => sheet.title === worksheetName) ? worksheetName : nextWorksheets[0]?.title || '';
      setAppliedSpreadsheetId(nextSource);
      setWorksheets(nextWorksheets);
      setSourceReady(true);
      setSourceRevision((current) => current + 1);
      if (nextName) await loadWorksheet(nextName, nextSource);
      else {
        setWorksheetName('');
        setColumns([]);
        setRows([]);
        setVisibleKeys([]);
      }
    } catch (err) {
      setSourceError(`刷新試算表失敗：${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [loadWorksheet, spreadsheetId, worksheetName]);

  useEffect(() => {
    if (spreadsheetId && !initialLoadRequestedRef.current) {
      initialLoadRequestedRef.current = true;
      refresh();
    }
  }, [refresh, spreadsheetId]);

  const handleSpreadsheetChange = (event) => {
    const nextValue = event.target.value;
    setSpreadsheetId(nextValue);
    if (nextValue.trim() !== appliedSpreadsheetId.trim()) {
      setSourceError('');
    }
  };

  const handleWorksheetChange = (nextWorksheet) => {
    if (nextWorksheet) loadWorksheet(nextWorksheet, appliedSpreadsheetId);
  };

  const visibleColumns = columns.filter((column) => visibleKeys.includes(column.key));
  const keyword = query.trim().toLocaleLowerCase('zh-TW');
  const displayDisabled = sourceStale || !sourceReady || loading;
  const filteredRows = sourceStale ? [] : rows.filter((row) => {
    const matchesPeople = !selectedTeam || (row.team === selectedTeam && selectedPeople.includes(row.person_option));
    const matchesQuery = !keyword || visibleColumns.some((column) => String(row.cells[column.index] ?? '').toLocaleLowerCase('zh-TW').includes(keyword));
    return matchesPeople && matchesQuery;
  });

  const handleCopy = async (row, column) => {
    try {
      await copyText(String(row.cells[column.index] ?? ''));
      setCopiedCell(`${row.row_number}:${column.key}`);
      setCopyStatus(`已複製第 ${row.row_number} 列「${column.label}」`);
    } catch (err) {
      setCopyStatus(`複製失敗：${err.message}`);
    }
  };

  const emptyMessage = sourceStale ? '資料來源已修改，請先按刷新套用。' : selectedTeam && !selectedPeople.length ? '目前未勾選人物，沒有符合資料。' : '目前篩選條件沒有資料。';

  return (
    <div className="section-gap sheet-copy-page">
      <header className="page-header">
        <h1 className="sheet-copy-title"><FileSpreadsheet size={28} /> Sheet 內容複製</h1>
        <p className="section-desc">先確認資料來源與工作表，再選擇團體、人物及要顯示的內容；所有篩選與顯示選項會即時記住，點擊任一儲存格即可原樣複製，包含換行。</p>
      </header>

      <SheetDataSourcePanel spreadsheetId={spreadsheetId} onSpreadsheetIdChange={handleSpreadsheetChange} worksheets={worksheets} worksheetName={worksheetName} onWorksheetChange={handleWorksheetChange} onRefresh={refresh} loading={loading} sourceReady={sourceReady} stale={sourceStale} error={sourceError} />

      <TeamPersonFilterPanel teams={sourceStale ? [] : teams} selectedTeam={sourceStale ? '' : selectedTeam} onTeamChange={setSelectedTeam} people={sourceStale ? [] : people} selectedPeople={sourceStale ? [] : selectedPeople} onSelectedPeopleChange={setSelectedPeople} loadingTeams={loadingTeams} loadingPeople={loadingPeople} error={teamPersonError} disabled={sourceStale || !sourceReady} teamEmptyLabel="全部團體" peopleDisabledMessage="未選定團體時顯示全部團體；請選擇團體後再篩選人物。" description="未選定團體時顯示全部團體；選定團體後只顯示已勾選的人物。" />
      {sharedFilterSaveError && <div className="filter-panel-status filter-panel-status-error" role="alert">{sharedFilterSaveError}；本機快取仍已保留。</div>}

      <section className="glass-panel card-padding sheet-copy-display-panel">
        <div className="filter-panel-header"><div><strong><Search size={17} aria-hidden="true" />顯示內容</strong><p>搜尋目前顯示欄位，並選擇要保留在資料表中的欄位。</p></div></div>
        <div className="sheet-copy-display-grid">
          <div className="form-group"><label className="form-label" htmlFor="sheet-copy-query"><Search size={14} />內容搜尋</label><input id="sheet-copy-query" className="form-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋顯示欄位" disabled={displayDisabled} /></div>
          <div className="sheet-copy-columns">
            <div className="sheet-copy-columns-head"><strong>顯示欄位（{visibleKeys.length} / {columns.length}）</strong><span><button type="button" onClick={() => setVisibleKeys(columns.map((column) => column.key))} disabled={displayDisabled}>全選</button><button type="button" onClick={() => setVisibleKeys([])} disabled={displayDisabled}>全不選</button></span></div>
            {!columns.length && <p className="filter-panel-status">請先刷新並選擇工作表。</p>}
            {!!columns.length && <div className="sheet-copy-column-grid">{columns.map((column) => <label key={column.key} className={visibleKeys.includes(column.key) ? 'selected' : ''}><input type="checkbox" checked={visibleKeys.includes(column.key)} disabled={displayDisabled} onChange={() => setVisibleKeys((current) => current.includes(column.key) ? current.filter((key) => key !== column.key) : [...current, column.key])} />{column.label}</label>)}</div>}
          </div>
        </div>
      </section>

      <section className="glass-panel sheet-copy-panel"><header><div><strong>{filteredRows.length} 列結果</strong><small>點擊儲存格即複製；不顯示遮住頁面的通知。</small></div><span aria-live="polite">{copyStatus}</span></header>
        {!visibleColumns.length ? <div className="sheet-copy-empty">請至少勾選一個欄位。</div> : !filteredRows.length ? <div className="sheet-copy-empty">{emptyMessage}</div> : <><div className="sheet-copy-scroll-hint" role="note">左右滑動查看完整欄位；列號固定在左側。</div><div className="sheet-copy-scroll"><table><thead><tr><th className="row-number">列</th>{visibleColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{filteredRows.map((row) => <tr key={row.row_number}><th className="row-number">{row.row_number}</th>{visibleColumns.map((column) => { const id = `${row.row_number}:${column.key}`; const copied = copiedCell === id; const value = String(row.cells[column.index] ?? ''); return <td key={column.key}><button type="button" className={`sheet-copy-cell ${copied ? 'copied' : ''}`} onClick={() => handleCopy(row, column)}><span>{value || <em>（空白）</em>}</span><small>{copied ? <><Check size={14} /> 已複製</> : <><Clipboard size={14} /> 複製</>}</small></button></td>; })}</tr>)}</tbody></table></div></>}
      </section>
    </div>
  );
}

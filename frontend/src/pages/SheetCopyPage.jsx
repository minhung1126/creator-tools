import React, { useEffect, useMemo, useState } from 'react';
import { Check, Clipboard, FileSpreadsheet, RefreshCw, Search } from 'lucide-react';
import { api } from '../services/api';

const STORAGE_KEY = 'creator-tools.sheet-copy.v1';

function readRemembered() {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('瀏覽器拒絕存取剪貼簿');
}

export default function SheetCopyPage({ sysSettings }) {
  const remembered = useMemo(readRemembered, []);
  const [spreadsheetId, setSpreadsheetId] = useState(remembered.spreadsheetId || sysSettings.default_spreadsheet_id || '');
  const [worksheets, setWorksheets] = useState([]);
  const [worksheetName, setWorksheetName] = useState(remembered.worksheetName || '');
  const [columns, setColumns] = useState([]);
  const [visibleColumnKeys, setVisibleColumnKeys] = useState(remembered.visibleColumnKeys || []);
  const [rows, setRows] = useState([]);
  const [teams, setTeams] = useState([]);
  const [selectedTeam, setSelectedTeam] = useState(remembered.selectedTeam || '');
  const [people, setPeople] = useState([]);
  const [selectedPerson, setSelectedPerson] = useState(remembered.selectedPerson || '');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copiedCell, setCopiedCell] = useState(null);
  const [copyStatus, setCopyStatus] = useState('');

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
      spreadsheetId,
      worksheetName,
      visibleColumnKeys,
      selectedTeam,
      selectedPerson,
    }));
  }, [spreadsheetId, worksheetName, visibleColumnKeys, selectedTeam, selectedPerson]);

  useEffect(() => {
    if (!copiedCell) return undefined;
    const timer = window.setTimeout(() => setCopiedCell(null), 1200);
    return () => window.clearTimeout(timer);
  }, [copiedCell]);

  const loadWorksheet = async (nextWorksheet, metadata = worksheets) => {
    if (!nextWorksheet) return;
    setLoading(true);
    setError('');
    try {
      const [options, table] = await Promise.all([
        api.parseSheetOptions(spreadsheetId, nextWorksheet),
        api.getCopyableSheetTable(spreadsheetId, nextWorksheet),
      ]);
      const nextColumns = table.columns || [];
      const rememberedKeys = visibleColumnKeys.filter((key) => nextColumns.some((column) => column.key === key));
      setColumns(nextColumns);
      setVisibleColumnKeys(rememberedKeys.length ? rememberedKeys : nextColumns.map((column) => column.key));
      setRows(table.rows || []);
      setTeams(options.teams || []);
      const nextTeam = (options.teams || []).includes(selectedTeam) ? selectedTeam : '';
      setSelectedTeam(nextTeam);
      setPeople([]);
      setSelectedPerson('');
      setWorksheetName(nextWorksheet);
      const selectedWorksheet = metadata.find((sheet) => sheet.title === nextWorksheet);
      if (!selectedWorksheet) setError('工作表已讀取，但 metadata 中找不到對應項目');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    if (!spreadsheetId.trim()) {
      setError('請先輸入主要試算表 ID 或網址');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const metadata = await api.getSpreadsheetMetadata(spreadsheetId);
      const nextWorksheets = metadata.worksheets || [];
      setWorksheets(nextWorksheets);
      const nextWorksheet = nextWorksheets.some((sheet) => sheet.title === worksheetName)
        ? worksheetName
        : (nextWorksheets[0]?.title || '');
      if (nextWorksheet) await loadWorksheet(nextWorksheet, nextWorksheets);
      else {
        setColumns([]);
        setRows([]);
        setTeams([]);
      }
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (spreadsheetId) refresh();
    // Initial hydration only; later source edits are applied by the explicit refresh button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeTeam = async (team) => {
    setSelectedTeam(team);
    setSelectedPerson('');
    setPeople([]);
    if (!team) return;
    try {
      const result = await api.getTeamPeople(spreadsheetId, worksheetName, team);
      setPeople(result.people || []);
    } catch (err) {
      setError(err.message);
    }
  };

  const visibleColumns = columns.filter((column) => visibleColumnKeys.includes(column.key));
  const filteredRows = rows.filter((row) => {
    if (selectedTeam && row.team !== selectedTeam) return false;
    if (selectedPerson && row.person_option !== selectedPerson) return false;
    if (!query.trim()) return true;
    const keyword = query.toLocaleLowerCase('zh-TW');
    return visibleColumns.some((column) => String(row.cells[column.index] || '').toLocaleLowerCase('zh-TW').includes(keyword));
  });

  const toggleColumn = (key) => {
    setVisibleColumnKeys((current) => current.includes(key)
      ? current.filter((item) => item !== key)
      : [...current, key]);
  };

  const copyCell = async (row, column) => {
    const text = String(row.cells[column.index] ?? '');
    try {
      await writeClipboard(text);
      setCopiedCell(`${row.row_number}:${column.key}`);
      setCopyStatus(`已複製第 ${row.row_number} 列「${column.label}」`);
    } catch (err) {
      setCopyStatus(`複製失敗：${err.message}`);
    }
  };

  return (
    <div className="section-gap">
      <div>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}><FileSpreadsheet size={28} /> Sheet 內容複製</h1>
        <p className="section-desc">依工作表、隊伍與人物篩選內容；點擊任一儲存格即可原樣複製，包含換行。</p>
      </div>

      <section className="top-filter-bar sheet-copy-controls">
        <div className="sheet-copy-source-row">
          <div className="form-group sheet-copy-source-input">
            <label className="form-label">主要試算表 ID / URL</label>
            <input className="form-input" value={spreadsheetId} onChange={(event) => setSpreadsheetId(event.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={refresh} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'spin' : ''} /> {loading ? '讀取中...' : '刷新工作表'}
          </button>
        </div>

        <div className="top-filter-grid">
          <div className="form-group">
            <label className="form-label">工作表</label>
            <select className="form-select" value={worksheetName} onChange={(event) => loadWorksheet(event.target.value)}>
              <option value="">請選擇工作表</option>
              {worksheets.map((sheet) => <option key={sheet.title} value={sheet.title}>{sheet.title}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">隊伍</label>
            <select className="form-select" value={selectedTeam} onChange={(event) => changeTeam(event.target.value)}>
              <option value="">全部隊伍</option>
              {teams.map((team) => <option key={team} value={team}>{team}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">人物</label>
            <select className="form-select" value={selectedPerson} onChange={(event) => setSelectedPerson(event.target.value)} disabled={!selectedTeam}>
              <option value="">全部人物</option>
              {people.map((person) => <option key={person} value={person}>{person}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label"><Search size={14} /> 內容篩選</label>
            <input className="form-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋目前顯示欄位" />
          </div>
        </div>

        {columns.length > 0 && (
          <div className="sheet-copy-column-picker">
            <div className="sheet-copy-column-heading">
              <strong>顯示欄位（{visibleColumnKeys.length} / {columns.length}）</strong>
              <div>
                <button type="button" onClick={() => setVisibleColumnKeys(columns.map((column) => column.key))}>全選</button>
                <button type="button" onClick={() => setVisibleColumnKeys([])}>全不選</button>
              </div>
            </div>
            <div className="sheet-copy-column-options">
              {columns.map((column) => (
                <label key={column.key} className={visibleColumnKeys.includes(column.key) ? 'is-selected' : ''}>
                  <input type="checkbox" checked={visibleColumnKeys.includes(column.key)} onChange={() => toggleColumn(column.key)} />
                  <span>{column.label}</span>
                </label>
              ))}
            </div>
          </div>
        )}
      </section>

      {error && <div className="glass-panel error-alert">{error}</div>}

      <section className="glass-panel sheet-copy-table-panel">
        <header className="sheet-copy-table-header">
          <div>
            <strong>{filteredRows.length} 列結果</strong>
            <span>點擊儲存格即複製，不會跳出遮住頁面的通知。</span>
          </div>
          <div className="sheet-copy-status" aria-live="polite">{copyStatus}</div>
        </header>

        {visibleColumns.length === 0 ? (
          <div className="sheet-copy-empty">請至少勾選一個顯示欄位。</div>
        ) : filteredRows.length === 0 ? (
          <div className="sheet-copy-empty">目前篩選條件沒有資料。</div>
        ) : (
          <div className="sheet-copy-table-scroll">
            <table className="sheet-copy-table">
              <thead>
                <tr>
                  <th className="sheet-copy-row-number">列</th>
                  {visibleColumns.map((column) => <th key={column.key}>{column.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <tr key={row.row_number}>
                    <th className="sheet-copy-row-number">{row.row_number}</th>
                    {visibleColumns.map((column) => {
                      const cellId = `${row.row_number}:${column.key}`;
                      const value = String(row.cells[column.index] ?? '');
                      const copied = copiedCell === cellId;
                      return (
                        <td key={column.key}>
                          <button
                            type="button"
                            className={`sheet-copy-cell ${copied ? 'is-copied' : ''}`}
                            onClick={() => copyCell(row, column)}
                            title={`點擊複製「${column.label}」`}
                          >
                            <span className="sheet-copy-cell-content">{value || <span className="sheet-copy-blank">（空白）</span>}</span>
                            <span className="sheet-copy-cell-action">{copied ? <><Check size={14} /> 已複製</> : <><Clipboard size={14} /> 複製</>}</span>
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

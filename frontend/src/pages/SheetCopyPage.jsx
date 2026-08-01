import React, { useEffect, useMemo, useState } from 'react';
import { Check, Clipboard, FileSpreadsheet, RefreshCw, Search } from 'lucide-react';
import { api } from '../services/api';
import SourceLinkInput from '../components/SourceLinkInput';

const STORAGE_KEY = 'creator-tools.sheet-copy.v1';
function loadSaved() { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { return {}; } }
async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const textarea = document.createElement('textarea'); textarea.value = text; textarea.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
  document.body.appendChild(textarea); textarea.select(); const copied = document.execCommand('copy'); textarea.remove();
  if (!copied) throw new Error('瀏覽器拒絕存取剪貼簿');
}

export default function SheetCopyPage({ sysSettings }) {
  const saved = useMemo(loadSaved, []);
  const [spreadsheetId, setSpreadsheetId] = useState(saved.spreadsheetId || sysSettings.default_spreadsheet_id || '');
  const [worksheets, setWorksheets] = useState([]); const [worksheetName, setWorksheetName] = useState(saved.worksheetName || '');
  const [columns, setColumns] = useState([]); const [visibleKeys, setVisibleKeys] = useState(saved.visibleKeys || []); const [rows, setRows] = useState([]);
  const [teams, setTeams] = useState([]); const [team, setTeam] = useState(saved.team || ''); const [people, setPeople] = useState([]); const [person, setPerson] = useState(saved.person || '');
  const [query, setQuery] = useState(''); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const [copiedCell, setCopiedCell] = useState(''); const [copyStatus, setCopyStatus] = useState('');

  useEffect(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify({ spreadsheetId, worksheetName, visibleKeys, team, person })); }, [spreadsheetId, worksheetName, visibleKeys, team, person]);
  useEffect(() => { if (!copiedCell) return undefined; const timer = setTimeout(() => setCopiedCell(''), 1200); return () => clearTimeout(timer); }, [copiedCell]);

  const loadPeople = async (sheetName, nextTeam, preferredPerson = '') => {
    setPeople([]); setPerson(''); if (!nextTeam) return;
    const result = await api.getTeamPeople(spreadsheetId, sheetName, nextTeam);
    const nextPeople = result.people || []; setPeople(nextPeople); setPerson(nextPeople.includes(preferredPerson) ? preferredPerson : '');
  };

  const loadWorksheet = async (name, preferredTeam = '', preferredPerson = '') => {
    if (!name) return; setLoading(true); setError('');
    try {
      const [options, table] = await Promise.all([api.parseSheetOptions(spreadsheetId, name), api.getCopyableSheetTable(spreadsheetId, name)]);
      const nextColumns = table.columns || []; const retained = visibleKeys.filter((key) => nextColumns.some((column) => column.key === key));
      const nextTeams = options.teams || []; const nextTeam = nextTeams.includes(preferredTeam) ? preferredTeam : '';
      setWorksheetName(name); setColumns(nextColumns); setVisibleKeys(retained.length ? retained : nextColumns.map((column) => column.key));
      setRows(table.rows || []); setTeams(nextTeams); setTeam(nextTeam); await loadPeople(name, nextTeam, preferredPerson);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  const refresh = async () => {
    if (!spreadsheetId.trim()) return setError('請先輸入主要試算表 ID 或網址'); setLoading(true); setError('');
    try {
      const metadata = await api.getSpreadsheetMetadata(spreadsheetId); const nextWorksheets = metadata.worksheets || []; setWorksheets(nextWorksheets);
      const nextName = nextWorksheets.some((sheet) => sheet.title === worksheetName) ? worksheetName : (nextWorksheets[0]?.title || '');
      if (nextName) await loadWorksheet(nextName, team, person); else { setColumns([]); setRows([]); setTeams([]); }
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  // Initial hydration only; later source edits are applied by the explicit refresh button.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (spreadsheetId) refresh(); }, []);
  const changeTeam = async (nextTeam) => { setTeam(nextTeam); try { await loadPeople(worksheetName, nextTeam); } catch (err) { setError(err.message); } };
  const visibleColumns = columns.filter((column) => visibleKeys.includes(column.key)); const keyword = query.trim().toLocaleLowerCase('zh-TW');
  const filteredRows = rows.filter((row) => (!team || row.team === team) && (!person || row.person_option === person) && (!keyword || visibleColumns.some((column) => String(row.cells[column.index] || '').toLocaleLowerCase('zh-TW').includes(keyword))));
  const handleCopy = async (row, column) => { try { await copyText(String(row.cells[column.index] ?? '')); setCopiedCell(`${row.row_number}:${column.key}`); setCopyStatus(`已複製第 ${row.row_number} 列「${column.label}」`); } catch (err) { setCopyStatus(`複製失敗：${err.message}`); } };

  return <div className="section-gap"><div><h1 className="sheet-copy-title"><FileSpreadsheet size={28} /> Sheet 內容複製</h1><p className="section-desc">選擇工作表、隊伍、人物與欄位；點擊任一儲存格即可原樣複製，包含換行。</p></div>
    <section className="top-filter-bar sheet-copy-controls"><div className="sheet-copy-source"><div className="form-group"><label className="form-label">主要試算表 ID / URL</label><SourceLinkInput value={spreadsheetId} onChange={(e) => setSpreadsheetId(e.target.value)} sourceType="spreadsheet" /></div><button className="btn btn-primary" onClick={refresh} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? '讀取中...' : '刷新工作表'}</button></div>
      <div className="top-filter-grid"><div className="form-group"><label className="form-label">工作表</label><select className="form-select" value={worksheetName} onChange={(e) => loadWorksheet(e.target.value)}><option value="">請選擇</option>{worksheets.map((sheet) => <option key={sheet.title}>{sheet.title}</option>)}</select></div><div className="form-group"><label className="form-label">隊伍</label><select className="form-select" value={team} onChange={(e) => changeTeam(e.target.value)}><option value="">全部隊伍</option>{teams.map((value) => <option key={value}>{value}</option>)}</select></div><div className="form-group"><label className="form-label">人物</label><select className="form-select" value={person} onChange={(e) => setPerson(e.target.value)} disabled={!team}><option value="">全部人物</option>{people.map((value) => <option key={value}>{value}</option>)}</select></div><div className="form-group"><label className="form-label"><Search size={14} /> 內容篩選</label><input className="form-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜尋顯示欄位" /></div></div>
      {columns.length > 0 && <div className="sheet-copy-columns"><div className="sheet-copy-columns-head"><strong>顯示欄位（{visibleKeys.length} / {columns.length}）</strong><span><button type="button" onClick={() => setVisibleKeys(columns.map((c) => c.key))}>全選</button><button type="button" onClick={() => setVisibleKeys([])}>全不選</button></span></div><div className="sheet-copy-column-grid">{columns.map((column) => <label key={column.key} className={visibleKeys.includes(column.key) ? 'selected' : ''}><input type="checkbox" checked={visibleKeys.includes(column.key)} onChange={() => setVisibleKeys((current) => current.includes(column.key) ? current.filter((key) => key !== column.key) : [...current, column.key])} />{column.label}</label>)}</div></div>}
    </section>{error && <div className="glass-panel error-alert">{error}</div>}
    <section className="glass-panel sheet-copy-panel"><header><div><strong>{filteredRows.length} 列結果</strong><small>點擊儲存格即複製；不顯示遮住頁面的通知。</small></div><span aria-live="polite">{copyStatus}</span></header>
      {!visibleColumns.length ? <div className="sheet-copy-empty">請至少勾選一個欄位。</div> : !filteredRows.length ? <div className="sheet-copy-empty">目前篩選條件沒有資料。</div> : <div className="sheet-copy-scroll"><table><thead><tr><th className="row-number">列</th>{visibleColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{filteredRows.map((row) => <tr key={row.row_number}><th className="row-number">{row.row_number}</th>{visibleColumns.map((column) => { const id = `${row.row_number}:${column.key}`; const copied = copiedCell === id; const value = String(row.cells[column.index] ?? ''); return <td key={column.key}><button type="button" className={`sheet-copy-cell ${copied ? 'copied' : ''}`} onClick={() => handleCopy(row, column)}><span>{value || <em>（空白）</em>}</span><small>{copied ? <><Check size={14} /> 已複製</> : <><Clipboard size={14} /> 複製</>}</small></button></td>; })}</tr>)}</tbody></table></div>}
    </section></div>;
}

import React, { useEffect, useRef } from 'react';
import { Users } from 'lucide-react';
import { EmptyState, StatusMessage } from './StatusMessage';

export default function TeamPersonFilterPanel({
  teams = [], selectedTeam = '', onTeamChange, people = [], selectedPeople = [], onSelectedPeopleChange,
  loading = false, loadingTeams = false, loadingPeople = false, error = '', disabled = false, teamEmptyLabel = '請選擇團體',
  peopleDisabled = false, peopleDisabledMessage = '請先選擇團體。', description = '先選擇團體，再勾選要使用的人物。',
}) {
  const selectAllRef = useRef(null);
  const validSelectedPeople = selectedPeople.filter((person) => people.includes(person));
  const allSelected = people.length > 0 && validSelectedPeople.length === people.length;
  const partiallySelected = validSelectedPeople.length > 0 && !allSelected;
  const teamsLoading = loading || loadingTeams;
  const peopleLoading = loading || loadingPeople;
  const peopleControlsDisabled = disabled || peopleDisabled || peopleLoading || !selectedTeam;
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = partiallySelected;
  }, [partiallySelected]);
  return (
    <section className={`filter-panel${disabled ? ' filter-panel-disabled' : ''}`}>
      <div className="filter-panel-header"><div><strong><Users size={17} aria-hidden="true" />團體與人物篩選</strong><p>{description}</p></div></div>
      <div className="filter-panel-grid filter-panel-team-grid">
        <div className="form-group">
          <label className="form-label" htmlFor="team-person-team">所屬團體</label>
          <select id="team-person-team" className="form-select" value={selectedTeam} onChange={(event) => onTeamChange(event.target.value)} disabled={disabled || teamsLoading || !teams.length}>
            <option value="">{teamEmptyLabel}</option>{teams.map((team) => <option key={team} value={team}>{team}</option>)}
          </select>
          {teamsLoading && <StatusMessage>讀取中…</StatusMessage>}
          {!teamsLoading && !disabled && !teams.length && <EmptyState>目前工作表沒有團體資料。</EmptyState>}
          {disabled && <EmptyState>請先刷新資料來源與工作表。</EmptyState>}
        </div>
      </div>
      <div className="filter-panel-people">
        <div className="filter-panel-people-header">
          <div><h2>人物選項篩選（已選 {validSelectedPeople.length} / {people.length}）</h2><p>只有勾選的人物會出現在頁面下方的選項中。</p></div>
          <label className="filter-select-all"><input ref={selectAllRef} type="checkbox" checked={allSelected} aria-checked={partiallySelected ? 'mixed' : allSelected} onChange={(event) => onSelectedPeopleChange(event.target.checked ? [...people] : [])} disabled={peopleControlsDisabled || !people.length} aria-label="全選或全不選人物" />全選 / 全不選</label>
        </div>
        {peopleLoading && <StatusMessage>讀取中…</StatusMessage>}
        {!peopleLoading && error && <StatusMessage tone="error" status="failed" title="人物資料讀取失敗">{error}</StatusMessage>}
        {!peopleLoading && !error && !selectedTeam && <EmptyState>{peopleDisabledMessage}</EmptyState>}
        {!peopleLoading && !error && selectedTeam && !people.length && <EmptyState>目前團體沒有可用人物。</EmptyState>}
        {!!people.length && <div className={`filter-option-grid${peopleControlsDisabled ? ' filter-option-grid-disabled' : ''}`}>
          {people.map((person) => {
            const selected = validSelectedPeople.includes(person);
            return <label key={person} className={`filter-option${selected ? ' filter-option-selected' : ''}`}><input type="checkbox" checked={selected} disabled={peopleControlsDisabled} onChange={() => onSelectedPeopleChange(selected ? validSelectedPeople.filter((item) => item !== person) : [...validSelectedPeople, person])} /><span>{person}</span></label>;
          })}
        </div>}
      </div>
    </section>
  );
}

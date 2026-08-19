import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import TeamPersonFilterPanel from './TeamPersonFilterPanel';

describe('TeamPersonFilterPanel', () => {
  const baseProps = {
    teams: ['團體 B', '團體 A'],
    selectedTeam: '團體 B',
    onTeamChange: vi.fn(),
    people: ['全團體', '乙', '甲'],
    selectedPeople: ['乙'],
    onSelectedPeopleChange: vi.fn(),
  };

  it('keeps API order and exposes a mixed select-all state', () => {
    render(<TeamPersonFilterPanel {...baseProps} />);

    expect(screen.getByRole('combobox')).toHaveTextContent('團體 B團體 A');
    expect(screen.getAllByRole('checkbox')).toHaveLength(4);
    expect(screen.getByRole('checkbox', { name: '全選或全不選人物' })).toHaveProperty('indeterminate', true);
  });

  it('toggles an entire person option and supports select all/none', () => {
    const onSelectedPeopleChange = vi.fn();
    const { rerender } = render(<TeamPersonFilterPanel {...baseProps} onSelectedPeopleChange={onSelectedPeopleChange} />);

    fireEvent.click(screen.getByLabelText('甲'));
    expect(onSelectedPeopleChange).toHaveBeenCalledWith(['乙', '甲']);

    fireEvent.click(screen.getByRole('checkbox', { name: '全選或全不選人物' }));
    expect(onSelectedPeopleChange).toHaveBeenLastCalledWith(['全團體', '乙', '甲']);
    rerender(<TeamPersonFilterPanel {...baseProps} selectedPeople={['全團體', '乙', '甲']} onSelectedPeopleChange={onSelectedPeopleChange} />);

    fireEvent.click(screen.getByRole('checkbox', { name: '全選或全不選人物' }));
    expect(onSelectedPeopleChange).toHaveBeenLastCalledWith([]);
  });

  it('shows disabled, loading, empty and error states', () => {
    const { rerender } = render(<TeamPersonFilterPanel {...baseProps} disabled />);
    expect(screen.getByText('請先刷新資料來源與工作表。')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toBeDisabled();

    rerender(<TeamPersonFilterPanel {...baseProps} loadingPeople />);
    expect(screen.getByText('讀取中…')).toBeInTheDocument();

    rerender(<TeamPersonFilterPanel {...baseProps} people={[]} error="讀取失敗" />);
    expect(screen.getByRole('alert')).toHaveTextContent('讀取失敗');

    rerender(<TeamPersonFilterPanel {...baseProps} selectedTeam="" people={[]} />);
    expect(screen.getByText('請先選擇團體。')).toBeInTheDocument();
  });
});

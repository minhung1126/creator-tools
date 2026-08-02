import { migrateSelectedPeople } from './SheetCopyPage';

describe('SheetCopyPage storage migration', () => {
  it('migrates the legacy single person value without losing array preferences', () => {
    expect(migrateSelectedPeople({ person: '甲' })).toEqual(['甲']);
    expect(migrateSelectedPeople({ selectedPeople: ['乙', '甲'], person: '舊值' })).toEqual(['乙', '甲']);
    expect(migrateSelectedPeople({})).toEqual([]);
  });
});


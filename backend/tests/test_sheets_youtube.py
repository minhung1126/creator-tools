from backend.app.api.youtube import resolve_assignment_row
from backend.app.services.sheets_service import matches_team_person, normalize_text, team_option_label


def test_sheet_matching_supports_unicode_and_whole_team(unicode_sheet_headers):
    team_header, person_header = unicode_sheet_headers
    row = {team_header: " A\u3000Team ", person_header: "\u200b"}
    assert normalize_text(row[team_header]) == "A Team"
    assert matches_team_person(row, "A Team", team_option_label("A Team"))


def test_duplicate_rows_only_pass_when_output_values_match():
    same = [{"title": "Title", "description": "Description"}, {"title": "Title", "description": "Description"}]
    conflict = [same[0], {"title": "Other", "description": "Description"}]
    assert resolve_assignment_row(same, "title", "description")[0] == same[0]
    assert resolve_assignment_row(conflict, "title", "description")[1] == "conflict"

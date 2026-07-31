import logging
import re
import unicodedata
from typing import Any, Dict, List

import googleapiclient.discovery
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

TEAM_OPTION_SUFFIX = "（全隊）"
_INVISIBLE_TEXT_CHARS = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")


def normalize_text(value: Any) -> Any:
    """Normalize Sheet/UI text for stable matching without changing non-string values."""
    if not isinstance(value, str):
        return value
    return unicodedata.normalize("NFKC", value).translate(_INVISIBLE_TEXT_CHARS).strip()


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Extract spreadsheet ID from a Google Sheets URL, or return as-is if already an ID."""
    if not url_or_id:
        return ""
    match = re.search(r"/d/([0-9a-zA-Z\-_]+)", url_or_id)
    if match:
        return match.group(1)
    return normalize_text(url_or_id)


def get_sheets_service(credentials: Credentials):
    return googleapiclient.discovery.build("sheets", "v4", credentials=credentials)


def quote_sheet_name(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"


def normalize_cell_value(value: Any) -> Any:
    """Normalize string cells so UI options and batch matching use identical values."""
    return normalize_text(value)


def team_option_label(team: str) -> str:
    """Return the UI label used for a team's whole-team Sheet row."""
    return f"{normalize_text(team)}{TEAM_OPTION_SUFFIX}"


def read_sheet_data(service, spreadsheet_id: str, range_name: str) -> List[Dict[str, Any]]:
    """Read a named range/sheet and return rows as dictionaries keyed by header."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        ).execute()
        rows = result.get("values", [])
        if not rows or len(rows) < 2:
            return []

        header = [normalize_text(col) for col in rows[0]]
        parsed_rows = []
        for row in rows[1:]:
            row_dict = {}
            for idx, cell_value in enumerate(row):
                if idx < len(header) and header[idx]:
                    row_dict[header[idx]] = normalize_cell_value(cell_value)
            parsed_rows.append(row_dict)
        return parsed_rows
    except Exception as exc:
        logger.error("Error reading sheet range '%s': %s", range_name, exc, exc_info=True)
        raise RuntimeError(f"無法讀取工作表範圍 {range_name}: {exc}") from exc


def get_sheet_headers(
    credentials: Credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
) -> List[str]:
    """Return normalized first-row headers for one worksheet."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{quote_sheet_name(worksheet_name)}!1:1",
    ).execute().get("values", [])
    return [normalize_text(value) for value in (values[0] if values else []) if normalize_text(value)]


def get_spreadsheet_metadata(credentials: Credentials, spreadsheet_id_or_url: str) -> Dict[str, Any]:
    """Return worksheet titles and the first-row column names for each worksheet."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="properties.title,sheets.properties.title",
    ).execute()

    worksheets = []
    for sheet in metadata.get("sheets", []):
        title = sheet.get("properties", {}).get("title")
        if not title:
            continue
        values = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(title)}!1:1",
        ).execute().get("values", [])
        columns = [normalize_text(value) for value in (values[0] if values else []) if normalize_text(value)]
        worksheets.append({"title": title, "columns": columns})

    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_title": metadata.get("properties", {}).get("title", ""),
        "worksheets": worksheets,
    }


def parse_options_from_sheets(
    credentials: Credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
) -> Dict[str, Any]:
    """Parse team options in their first-appearance order in the selected worksheet."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    rows = read_sheet_data(service, spreadsheet_id, quote_sheet_name(worksheet_name))
    teams = [normalize_text(row.get("所屬團體")) for row in rows if row.get("所屬團體")]
    return {
        "spreadsheet_id": spreadsheet_id,
        "worksheet_name": worksheet_name,
        "teams": list(dict.fromkeys(teams)),
        "row_count": len(rows),
    }


def get_people_for_team(
    credentials: Credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
    team: str,
) -> List[str]:
    """Return person and whole-team options in the worksheet's exact row order."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    rows = read_sheet_data(service, spreadsheet_id, quote_sheet_name(worksheet_name))
    normalized_team = normalize_text(team)
    options = []
    for row in rows:
        if normalize_text(row.get("所屬團體") or "") != normalized_team:
            continue
        person = normalize_text(row.get("人") or "")
        options.append(person or team_option_label(normalized_team))
    return list(dict.fromkeys(options))


def get_all_rows_for_sheet(
    credentials: Credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
) -> List[Dict[str, Any]]:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    return read_sheet_data(service, spreadsheet_id, quote_sheet_name(worksheet_name))

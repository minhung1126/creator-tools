import logging
import re
from typing import Any, Dict, List

import googleapiclient.discovery
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Extract spreadsheet ID from a Google Sheets URL, or return as-is if already an ID."""
    if not url_or_id:
        return ""
    match = re.search(r"/d/([0-9a-zA-Z\-_]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()


def get_sheets_service(credentials: Credentials):
    return googleapiclient.discovery.build("sheets", "v4", credentials=credentials)


def quote_sheet_name(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"


def normalize_cell_value(value: Any) -> Any:
    """Trim string cells so UI options and batch matching use identical values."""
    return value.strip() if isinstance(value, str) else value


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

        header = [str(col).strip() for col in rows[0]]
        parsed_rows = []
        for row in rows[1:]:
            row_dict = {}
            for idx, cell_value in enumerate(row):
                if idx < len(header):
                    row_dict[header[idx]] = normalize_cell_value(cell_value)
            parsed_rows.append(row_dict)
        return parsed_rows
    except Exception as exc:
        logger.error("Error reading sheet range '%s': %s", range_name, exc, exc_info=True)
        return []


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
        columns = [str(value).strip() for value in (values[0] if values else []) if str(value).strip()]
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
    """Parse team options from one selected worksheet."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    rows = read_sheet_data(service, spreadsheet_id, quote_sheet_name(worksheet_name))
    teams = sorted({str(row.get("所屬團體")).strip() for row in rows if row.get("所屬團體")})
    return {
        "spreadsheet_id": spreadsheet_id,
        "worksheet_name": worksheet_name,
        "teams": teams,
        "row_count": len(rows),
    }


def get_people_for_team(
    credentials: Credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
    team: str,
) -> List[str]:
    """Get unique people names for a team from the selected worksheet."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    rows = read_sheet_data(service, spreadsheet_id, quote_sheet_name(worksheet_name))
    normalized_team = team.strip()
    people = [
        str(row.get("人")).strip()
        for row in rows
        if row.get("所屬團體") == normalized_team and row.get("人")
    ]
    return list(dict.fromkeys(people))


def get_all_rows_for_sheet(
    credentials: Credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
) -> List[Dict[str, Any]]:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    return read_sheet_data(service, spreadsheet_id, quote_sheet_name(worksheet_name))

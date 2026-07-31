import re
import logging
from typing import List, Dict, Any

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


def read_sheet_data(service, spreadsheet_id: str, range_name: str) -> List[Dict[str, Any]]:
    """Read a named range/sheet and return rows as list of dicts keyed by header."""
    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        rows = result.get("values", [])
        if not rows or len(rows) < 2:
            return []

        header = [str(col).strip() for col in rows[0]]
        parsed_rows = []
        for row in rows[1:]:
            row_dict = {}
            for idx, cell_value in enumerate(row):
                if idx < len(header):
                    row_dict[header[idx]] = cell_value
            parsed_rows.append(row_dict)
        return parsed_rows
    except Exception as e:
        logger.error("Error reading sheet range '%s': %s", range_name, e, exc_info=True)
        return []


def parse_options_from_sheets(credentials: Credentials, spreadsheet_id_or_url: str) -> Dict[str, Any]:
    """Parse team/group options from both Video and Shorts worksheets."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)

    video_rows = read_sheet_data(service, spreadsheet_id, "Youtube Video")
    shorts_rows = read_sheet_data(service, spreadsheet_id, "Youtube Shorts")

    video_teams = [r.get("所屬團體") for r in video_rows if r.get("所屬團體")]
    shorts_teams = [r.get("所屬團體") for r in shorts_rows if r.get("所屬團體")]

    teams = sorted(list(set(video_teams + shorts_teams)))

    return {
        "spreadsheet_id": spreadsheet_id,
        "teams": teams,
        "video_count": len(video_rows),
        "shorts_count": len(shorts_rows)
    }


def get_people_for_team(credentials: Credentials, spreadsheet_id_or_url: str, video_type: str, team: str) -> List[str]:
    """Get list of people names for a specific team and video type."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)

    sheet_name = "Youtube Video" if video_type.lower() == "video" else "Youtube Shorts"
    rows = read_sheet_data(service, spreadsheet_id, sheet_name)

    people = []
    for r in rows:
        if r.get("所屬團體") == team and r.get("人"):
            people.append(r.get("人"))

    return sorted(list(set(people)))


def get_all_rows_for_type(credentials: Credentials, spreadsheet_id_or_url: str, video_type: str) -> List[Dict[str, Any]]:
    """Get all data rows for a specific video type worksheet."""
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    service = get_sheets_service(credentials)
    sheet_name = "Youtube Video" if video_type.lower() == "video" else "Youtube Shorts"
    return read_sheet_data(service, spreadsheet_id, sheet_name)

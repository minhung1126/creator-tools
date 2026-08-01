import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.services.sheets_service import (
    get_copyable_sheet_table,
    get_people_for_team,
    get_random_member_preview,
    get_spreadsheet_metadata,
    parse_options_from_sheets,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sheets", tags=["Google Sheets"])


class SpreadsheetInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""


class ParseSheetsInput(SpreadsheetInput):
    worksheet_name: str


class GetPeopleInput(SpreadsheetInput):
    worksheet_name: str
    team: str


class RandomMemberPreviewInput(GetPeopleInput):
    columns: List[str]


def resolve_spreadsheet_id(value: Optional[str]) -> str:
    target_id = value or runtime_config.get("default_spreadsheet_id")
    if not target_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")
    return target_id


@router.post("/metadata")
def spreadsheet_metadata(
    payload: SpreadsheetInput,
    creds: Credentials = Depends(require_credentials),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id)
    try:
        return get_spreadsheet_metadata(creds, target_id)
    except Exception as exc:
        logger.error("Failed to read spreadsheet metadata: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read spreadsheet metadata: {str(exc)}") from exc


@router.post("/parse-options")
def parse_sheet_teams(
    payload: ParseSheetsInput,
    creds: Credentials = Depends(require_credentials),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id)
    try:
        return parse_options_from_sheets(creds, target_id, payload.worksheet_name)
    except Exception as exc:
        logger.error("Failed to parse Google Sheet: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to parse Google Sheet: {str(exc)}") from exc


@router.post("/people")
def get_team_people(
    payload: GetPeopleInput,
    creds: Credentials = Depends(require_credentials),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id)
    try:
        people = get_people_for_team(creds, target_id, payload.worksheet_name, payload.team)
        return {
            "team": payload.team,
            "worksheet_name": payload.worksheet_name,
            "people": people,
        }
    except Exception as exc:
        logger.error("Failed to read people from sheet: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read people from sheet: {str(exc)}") from exc


@router.post("/random-member-preview")
def random_member_preview(
    payload: RandomMemberPreviewInput,
    creds: Credentials = Depends(require_credentials),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id)
    try:
        return get_random_member_preview(
            creds,
            target_id,
            payload.worksheet_name,
            payload.team,
            payload.columns,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to build random member preview: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build random member preview: {str(exc)}") from exc


@router.post("/copy-table")
def copyable_sheet_table(
    payload: ParseSheetsInput,
    creds: Credentials = Depends(require_credentials),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id)
    try:
        return get_copyable_sheet_table(creds, target_id, payload.worksheet_name)
    except Exception as exc:
        logger.error("Failed to read copyable Sheet table: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read Google Sheet: {str(exc)}") from exc

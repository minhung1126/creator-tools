import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field

from backend.app.core.account_state import get_account_setting
from backend.app.core.dependencies import require_account_subject, require_login_credentials
from backend.app.core.error_contract import http_error
from backend.app.services.provider_errors import map_google_sheets_error
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
    spreadsheet_url_or_id: Optional[str] = Field(default="", max_length=512)


class ParseSheetsInput(SpreadsheetInput):
    worksheet_name: str = Field(min_length=1, max_length=200)


class GetPeopleInput(SpreadsheetInput):
    worksheet_name: str = Field(min_length=1, max_length=200)
    team: str = Field(min_length=1, max_length=200)


class RandomMemberPreviewInput(GetPeopleInput):
    columns: List[Annotated[str, Field(max_length=200)]] = Field(max_length=50)


def resolve_spreadsheet_id(value: Optional[str], owner_sub: str) -> str:
    target_id = value or get_account_setting(owner_sub, "default_spreadsheet_id", "")
    if not target_id:
        raise http_error(400, "spreadsheet_required", "請提供試算表 ID 或網址。")
    return target_id


@router.post("/metadata")
def spreadsheet_metadata(
    payload: SpreadsheetInput,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id, owner_sub)
    try:
        return get_spreadsheet_metadata(creds, target_id)
    except Exception as exc:
        logger.error("Failed to read spreadsheet metadata: %s", type(exc).__name__)
        raise map_google_sheets_error(exc, operation="metadata").to_http_exception() from exc


@router.post("/parse-options")
def parse_sheet_teams(
    payload: ParseSheetsInput,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id, owner_sub)
    try:
        return parse_options_from_sheets(creds, target_id, payload.worksheet_name)
    except Exception as exc:
        logger.error("Failed to parse Google Sheet: %s", type(exc).__name__)
        raise map_google_sheets_error(exc, operation="parse_options").to_http_exception() from exc


@router.post("/people")
def get_team_people(
    payload: GetPeopleInput,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id, owner_sub)
    try:
        people = get_people_for_team(creds, target_id, payload.worksheet_name, payload.team)
        return {"team": payload.team, "worksheet_name": payload.worksheet_name, "people": people}
    except Exception as exc:
        logger.error("Failed to read people from sheet: %s", type(exc).__name__)
        raise map_google_sheets_error(exc, operation="people").to_http_exception() from exc


@router.post("/random-member-preview")
def random_member_preview(
    payload: RandomMemberPreviewInput,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id, owner_sub)
    try:
        return get_random_member_preview(creds, target_id, payload.worksheet_name, payload.team, payload.columns)
    except ValueError as exc:
        raise http_error(404, "sheets_member_not_found", "找不到符合條件的工作表成員資料。") from exc
    except Exception as exc:
        logger.error("Failed to build random member preview: %s", type(exc).__name__)
        raise map_google_sheets_error(exc, operation="random_member_preview").to_http_exception() from exc


@router.post("/copy-table")
def copyable_sheet_table(
    payload: ParseSheetsInput,
    creds: Credentials = Depends(require_login_credentials),
    owner_sub: str = Depends(require_account_subject),
):
    target_id = resolve_spreadsheet_id(payload.spreadsheet_url_or_id, owner_sub)
    try:
        return get_copyable_sheet_table(creds, target_id, payload.worksheet_name)
    except Exception as exc:
        logger.error("Failed to read copyable Sheet table: %s", type(exc).__name__)
        raise map_google_sheets_error(exc, operation="copy_table").to_http_exception() from exc

import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, Field

from backend.app.core.account_state import get_account_setting
from backend.app.core.dependencies import require_account_subject, require_login_credentials
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
    spreadsheet_url_or_id: Optional[str] = Field(default="", max_length=512)


class ParseSheetsInput(SpreadsheetInput):
    worksheet_name: str = Field(min_length=1, max_length=200)


class GetPeopleInput(SpreadsheetInput):
    worksheet_name: str = Field(min_length=1, max_length=200)
    team: str = Field(min_length=1, max_length=200)


class RandomMemberPreviewInput(GetPeopleInput):
    columns: List[Annotated[str, Field(max_length=200)]] = Field(max_length=50)


def resolve_spreadsheet_id(value: Optional[str], owner_sub: str | None = None) -> str:
    target_id = value or get_account_setting(
        owner_sub,
        "default_spreadsheet_id",
        runtime_config.get("default_spreadsheet_id") if not owner_sub else "",
    )
    if not target_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")
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
        raise HTTPException(status_code=500, detail="無法讀取試算表資訊，請稍後再試。") from exc


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
        raise HTTPException(status_code=500, detail="無法讀取工作表資料，請稍後再試。") from exc


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
        raise HTTPException(status_code=500, detail="無法讀取工作表成員資料，請稍後再試。") from exc


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
        raise HTTPException(status_code=404, detail="找不到符合條件的工作表成員資料。") from exc
    except Exception as exc:
        logger.error("Failed to build random member preview: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="無法建立隨機成員預覽，請稍後再試。") from exc


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
        raise HTTPException(status_code=500, detail="無法讀取工作表內容，請稍後再試。") from exc

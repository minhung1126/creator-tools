import logging

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from google.oauth2.credentials import Credentials

from backend.app.core.dependencies import require_credentials
from backend.app.core.runtime_config import runtime_config
from backend.app.services.sheets_service import (
    parse_options_from_sheets,
    get_people_for_team,
    extract_spreadsheet_id
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sheets", tags=["Google Sheets"])


class ParseSheetsInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""


class GetPeopleInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""
    video_type: str = "Video"  # "Video" or "Shorts"
    team: str


@router.post("/parse-options")
def parse_sheet_teams(
    payload: ParseSheetsInput,
    creds: Credentials = Depends(require_credentials)
):
    target_id = payload.spreadsheet_url_or_id or runtime_config.get("default_spreadsheet_id")
    if not target_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")

    try:
        data = parse_options_from_sheets(creds, target_id)
        return data
    except Exception as e:
        logger.error("Failed to parse Google Sheet: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to parse Google Sheet: {str(e)}")


@router.post("/people")
def get_team_people(
    payload: GetPeopleInput,
    creds: Credentials = Depends(require_credentials)
):
    target_id = payload.spreadsheet_url_or_id or runtime_config.get("default_spreadsheet_id")
    if not target_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")

    try:
        people = get_people_for_team(creds, target_id, payload.video_type, payload.team)
        return {
            "team": payload.team,
            "video_type": payload.video_type,
            "people": people
        }
    except Exception as e:
        logger.error("Failed to read people from sheet: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read people from sheet: {str(e)}")

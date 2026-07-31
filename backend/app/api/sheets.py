from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.app.core.config import settings
from backend.app.core.security import decrypt_session_data
from backend.app.services.google_auth import get_current_credentials
from backend.app.services.sheets_service import (
    parse_options_from_sheets,
    get_people_for_team,
    extract_spreadsheet_id
)

router = APIRouter(prefix="/sheets", tags=["Google Sheets"])

class ParseSheetsInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""

class GetPeopleInput(BaseModel):
    spreadsheet_url_or_id: Optional[str] = ""
    video_type: str = "Video" # "Video" or "Shorts"
    team: str

def require_credentials(request: Request):
    cookie = request.cookies.get("creator_tools_session")
    stored_tokens = decrypt_session_data(cookie) if cookie else None
    creds = get_current_credentials(stored_tokens)
    if not creds or not creds.valid:
        raise HTTPException(
            status_code=401,
            detail="Google account not connected or OAuth token expired. Please connect your Google account in Settings."
        )
    return creds

@router.post("/parse-options")
def parse_sheet_teams(payload: ParseSheetsInput, request: Request):
    creds = require_credentials(request)
    target_id = payload.spreadsheet_url_or_id or settings.DEFAULT_SPREADSHEET_ID
    if not target_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID or URL is required.")
        
    try:
        data = parse_options_from_sheets(creds, target_id)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Google Sheet: {str(e)}")

@router.post("/people")
def get_team_people(payload: GetPeopleInput, request: Request):
    creds = require_credentials(request)
    target_id = payload.spreadsheet_url_or_id or settings.DEFAULT_SPREADSHEET_ID
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
        raise HTTPException(status_code=500, detail=f"Failed to read people from sheet: {str(e)}")

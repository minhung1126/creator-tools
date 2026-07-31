from fastapi import APIRouter, Request, Response, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
from backend.app.core.config import settings
from backend.app.core.security import encrypt_session_data, decrypt_session_data
from backend.app.services.google_auth import (
    get_auth_url,
    exchange_code_for_tokens,
    get_current_credentials,
    clear_current_credentials
)

router = APIRouter(prefix="/auth", tags=["Google OAuth"])

class ClientCredentialsInput(BaseModel):
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""

@router.get("/config")
def get_auth_config():
    redirect_uri = settings.get_redirect_uri()
    return {
        "host": settings.HOST,
        "frontend_url": settings.FRONTEND_URL,
        "redirect_uri": redirect_uri,
        "has_client_id": bool(settings.GOOGLE_CLIENT_ID),
        "has_client_secret": bool(settings.GOOGLE_CLIENT_SECRET),
        "client_id_preview": f"{settings.GOOGLE_CLIENT_ID[:12]}..." if settings.GOOGLE_CLIENT_ID else "Not Set",
        "scopes": [
            "Google Sheets API",
            "YouTube Data API v3",
            "Google Drive API"
        ]
    }

@router.get("/url")
def get_google_auth_url(client_id: str = "", client_secret: str = ""):
    cid = client_id or settings.GOOGLE_CLIENT_ID
    csec = client_secret or settings.GOOGLE_CLIENT_SECRET
    if not cid or not csec:
        raise HTTPException(
            status_code=400,
            detail="Google Client ID and Client Secret are not configured. Please set them in .env or Settings page."
        )
    try:
        url = get_auth_url(client_id=cid, client_secret=csec)
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
def google_oauth_callback(code: str = Query(...), error: Optional[str] = None):
    if error:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/#auth_error={error}")
    try:
        token_dict = exchange_code_for_tokens(code=code)
        encrypted_cookie = encrypt_session_data(token_dict)
        
        response = RedirectResponse(url=f"{settings.FRONTEND_URL}/#auth_success=1")
        response.set_cookie(
            key="creator_tools_session",
            value=encrypted_cookie,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return response
    except Exception as e:
        print(f"Callback error: {e}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/#auth_error={str(e)}")

@router.get("/user")
def get_user_status(request: Request):
    # Check cookie or token cache
    cookie = request.cookies.get("creator_tools_session")
    stored_tokens = decrypt_session_data(cookie) if cookie else None
    
    creds = get_current_credentials(stored_tokens)
    if not creds or not creds.valid:
        return {
            "authenticated": False,
            "user": None
        }
        
    user_info = stored_tokens.get("user", {}) if stored_tokens else {"email": "Authenticated User"}
    return {
        "authenticated": True,
        "user": user_info,
        "token_expired": creds.expired
    }

@router.post("/logout")
def logout(response: Response):
    clear_current_credentials()
    res = Response(content='{"status":"logged_out"}', media_type="application/json")
    res.delete_cookie("creator_tools_session")
    return res

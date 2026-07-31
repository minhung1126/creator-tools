"""
Shared FastAPI Dependencies

Centralizes common dependency injection functions used across API routes.
"""

import logging

from fastapi import Request, HTTPException
from google.oauth2.credentials import Credentials

from backend.app.core.security import decrypt_session_data
from backend.app.services.google_auth import get_current_credentials

logger = logging.getLogger(__name__)


def require_credentials(request: Request) -> Credentials:
    """
    FastAPI dependency that extracts and validates Google OAuth credentials
    from the session cookie. Raises 401 if not authenticated.
    """
    cookie = request.cookies.get("creator_tools_session")
    stored_tokens = decrypt_session_data(cookie) if cookie else None
    creds = get_current_credentials(stored_tokens)

    if not creds or not creds.valid:
        logger.warning("Unauthorized API access attempt")
        raise HTTPException(
            status_code=401,
            detail="Google account not connected or OAuth token expired. "
                   "Please connect your Google account in Settings."
        )
    return creds

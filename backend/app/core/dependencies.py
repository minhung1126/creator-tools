"""
Shared FastAPI Dependencies

Centralizes common dependency injection functions used across API routes.
"""

import logging

from fastapi import HTTPException, Request
from google.oauth2.credentials import Credentials

from backend.app.services.google_auth import get_current_credentials

logger = logging.getLogger(__name__)


def require_credentials(request: Request) -> Credentials:
    """
    FastAPI dependency that extracts and validates Google OAuth credentials
    from the session cookie. Raises 401 if not authenticated.
    """
    session_id = request.cookies.get("creator_tools_session")
    creds = get_current_credentials(session_id)

    if not creds or not creds.valid:
        logger.warning("Unauthorized API access attempt")
        raise HTTPException(
            status_code=401,
            detail="Google account not connected or OAuth token expired. "
            "Please connect your Google account in Settings.",
        )
    return creds

from typing import Any

from itsdangerous import BadData, BadSignature, URLSafeTimedSerializer

from backend.app.core.config import settings

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
GOOGLE_OAUTH_STATE_SALT = "google-oauth-state"
INSTAGRAM_OAUTH_STATE_SALT = "instagram-oauth-state"


def sign_timed_data(data: dict[str, Any], salt: str) -> str:
    """Sign short-lived, non-session state for a single OAuth flow."""
    return serializer.dumps(data, salt=salt)


def verify_timed_data(token_str: str, salt: str, max_age: int) -> dict | None:
    """Verify and decode short-lived signed data."""
    try:
        data = serializer.loads(token_str, max_age=max_age, salt=salt)
        return data
    except (BadSignature, BadData):
        return None

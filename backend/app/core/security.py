import json
import base64
from itsdangerous import URLSafeTimedSerializer, BadSignature
from backend.app.core.config import settings

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)

def encrypt_session_data(data: dict) -> str:
    """Encrypt session token dictionary to a URL-safe signed string."""
    return serializer.dumps(data)

def decrypt_session_data(token_str: str, max_age: int = 60 * 60 * 24 * 7) -> dict | None:
    """Decrypt and verify signed session string."""
    try:
        data = serializer.loads(token_str, max_age=max_age)
        return data
    except BadSignature:
        return None

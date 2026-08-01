import warnings
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

INSTAGRAM_API_VERSION = "v25.0"


class Settings(BaseSettings):
    BIND_HOST: str = "0.0.0.0"
    PORT: int = 8000
    PUBLIC_BASE_URL: str = ""
    FRONTEND_URL: str = ""

    # Read for one migration cycle only. It never controls binding or URLs.
    HOST: str = ""

    # Access is intentionally single-admin. Keep this comma-separated so the
    # same .env works with pydantic-settings and Docker.
    ALLOWED_GOOGLE_EMAILS: str = ""

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    SECRET_KEY: str = "creator-tools-super-secret-key-change-in-production-2026"
    CREDENTIAL_ENCRYPTION_KEY: str = ""

    DEFAULT_SPREADSHEET_ID: str = ""
    DEFAULT_PLAYLIST_ID: str = ""

    INSTAGRAM_APP_ID: str = ""
    INSTAGRAM_APP_SECRET: str = ""

    # Legacy names are read only to emit a migration warning. They are never
    # used as application credentials.
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""

    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_BASE_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context) -> None:
        if not self.PUBLIC_BASE_URL:
            legacy_host = self.HOST.strip()
            if legacy_host:
                scheme = "http" if legacy_host in {"localhost", "127.0.0.1", "0.0.0.0"} else "https"
                port = f":{self.PORT}" if scheme == "http" else ""
                self.PUBLIC_BASE_URL = f"{scheme}://{legacy_host}{port}"
            else:
                self.PUBLIC_BASE_URL = f"http://localhost:{self.PORT}"
        if not self.FRONTEND_URL:
            parsed = urlparse(self.PUBLIC_BASE_URL)
            if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                self.FRONTEND_URL = "http://localhost:3000"
            else:
                self.FRONTEND_URL = self.PUBLIC_BASE_URL

    @property
    def is_production(self) -> bool:
        parsed = urlparse(self.PUBLIC_BASE_URL)
        return parsed.scheme.lower() == "https" or parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            None,
        }

    @property
    def cookie_secure(self) -> bool:
        return urlparse(self.PUBLIC_BASE_URL).scheme.lower() == "https"

    @property
    def scheme(self) -> str:
        return urlparse(self.PUBLIC_BASE_URL).scheme.lower()

    @property
    def base_url(self) -> str:
        return self.PUBLIC_BASE_URL.rstrip("/")

    @property
    def frontend_url(self) -> str:
        return self.FRONTEND_URL.rstrip("/")

    @property
    def allowed_google_emails(self) -> frozenset[str]:
        return frozenset(
            email.strip().casefold()
            for email in self.ALLOWED_GOOGLE_EMAILS.split(",")
            if email.strip()
        )

    def is_google_email_allowed(self, email: str) -> bool:
        return bool(email) and email.strip().casefold() in self.allowed_google_emails

    @property
    def instagram_app_id(self) -> str:
        return self.INSTAGRAM_APP_ID

    @property
    def instagram_app_secret(self) -> str:
        return self.INSTAGRAM_APP_SECRET

    @property
    def instagram_api_version(self) -> str:
        return INSTAGRAM_API_VERSION

    def get_redirect_uri(self) -> str:
        return f"{self.base_url}/api/v1/auth/callback"

    def get_instagram_redirect_uri(self) -> str:
        return f"{self.base_url}/api/v1/instagram/auth/callback"


settings = Settings()

if settings.SECRET_KEY == "creator-tools-super-secret-key-change-in-production-2026":
    warnings.warn(
        "Using the default SECRET_KEY; set a unique value before production.",
        stacklevel=2,
    )

if settings.HOST:
    warnings.warn(
        "HOST is deprecated; migrate to BIND_HOST and PUBLIC_BASE_URL.",
        DeprecationWarning,
        stacklevel=2,
    )

if settings.META_APP_ID or settings.META_APP_SECRET:
    warnings.warn(
        "META_APP_ID/META_APP_SECRET are deprecated and ignored; use INSTAGRAM_APP_ID/INSTAGRAM_APP_SECRET.",
        DeprecationWarning,
        stacklevel=2,
    )

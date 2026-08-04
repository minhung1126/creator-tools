import hashlib
import secrets
import warnings
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Do not infer the deployment environment from the hostname. A public
    # development instance must not accidentally receive production policy,
    # and a production instance must opt in explicitly and fail closed.
    ENVIRONMENT: str = "development"
    BIND_HOST: str = "0.0.0.0"
    PORT: int = 8000
    PUBLIC_BASE_URL: str = ""
    FRONTEND_URL: str = ""
    TRUSTED_HOSTS: str = ""

    # Access is intentionally single-admin. Keep this comma-separated so the
    # same .env works with pydantic-settings and Docker. This must stay in the
    # server environment because it is needed before the user can open the UI.
    ALLOWED_GOOGLE_EMAILS: str = ""

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    SECRET_KEY: str = ""
    CREDENTIAL_ENCRYPTION_KEY: str = ""

    # YouTube quota policy values are persisted from the authenticated
    # settings page; these environment defaults are only the first-run
    # fallback and never contain secrets.
    YOUTUBE_GENERAL_QUOTA_LIMIT: int = 10_000
    YOUTUBE_QUOTA_SAFETY_BUFFER_UNITS: int = 1_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context) -> None:
        del __context
        self.ENVIRONMENT = self.ENVIRONMENT.strip().casefold()
        if self.ENVIRONMENT not in {"development", "test", "staging", "production"}:
            raise ValueError("ENVIRONMENT must be one of development, test, staging, or production")

        if not self.PUBLIC_BASE_URL:
            self.PUBLIC_BASE_URL = f"http://localhost:{self.PORT}"
        if not self.FRONTEND_URL:
            parsed = urlparse(self.PUBLIC_BASE_URL)
            if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                self.FRONTEND_URL = "http://localhost:3000"
            else:
                self.FRONTEND_URL = self.PUBLIC_BASE_URL

        if not self.SECRET_KEY:
            if self.is_production:
                raise ValueError("SECRET_KEY must be explicitly configured in production")
            self.SECRET_KEY = secrets.token_urlsafe(32)
            warnings.warn("SECRET_KEY is not configured; using an ephemeral development key.", stacklevel=2)

        if not self.CREDENTIAL_ENCRYPTION_KEY:
            if self.is_production:
                raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be explicitly configured in production")
            # Keep local development usable without silently reusing the
            # signing key. This value remains stable for the lifetime of the
            # process; production must provide a dedicated persistent key.
            self.CREDENTIAL_ENCRYPTION_KEY = hashlib.sha256(
                f"{self.SECRET_KEY}:credential-encryption".encode("utf-8")
            ).hexdigest()
            warnings.warn(
                "CREDENTIAL_ENCRYPTION_KEY is not configured; using a derived development key.",
                stacklevel=2,
            )

        if self.CREDENTIAL_ENCRYPTION_KEY == self.SECRET_KEY:
            if self.is_production:
                raise ValueError("SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY must be different in production")
            self.CREDENTIAL_ENCRYPTION_KEY = hashlib.sha256(
                f"{self.SECRET_KEY}:credential-encryption".encode("utf-8")
            ).hexdigest()
            warnings.warn(
                "SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY matched; derived a separate development key.",
                stacklevel=2,
            )

        if self.is_production:
            self._require_https("PUBLIC_BASE_URL", self.PUBLIC_BASE_URL)
            self._require_https("FRONTEND_URL", self.FRONTEND_URL)
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must contain at least 32 characters in production")
            if len(self.CREDENTIAL_ENCRYPTION_KEY) < 32:
                raise ValueError("CREDENTIAL_ENCRYPTION_KEY must contain at least 32 characters in production")
            if not self.allowed_google_emails:
                raise ValueError("ALLOWED_GOOGLE_EMAILS must contain at least one account in production")

    @staticmethod
    def _require_https(name: str, value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"{name} must be an HTTPS URL without embedded credentials in production")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production or urlparse(self.PUBLIC_BASE_URL).scheme.lower() == "https"

    @property
    def allowlist_required(self) -> bool:
        # HTTPS deployments are treated conservatively even when an operator
        # has not opted into the full production profile yet. This is a safety
        # gate, not environment detection; ``is_production`` remains explicit.
        return self.is_production or self.scheme == "https"

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
    def trusted_hosts(self) -> tuple[str, ...]:
        configured = tuple(host.strip() for host in self.TRUSTED_HOSTS.split(",") if host.strip())
        if configured:
            return configured
        parsed = urlparse(self.PUBLIC_BASE_URL)
        defaults = {parsed.hostname} if parsed.hostname else set()
        if not self.is_production:
            defaults.update({"localhost", "127.0.0.1", "0.0.0.0", "testserver"})
        return tuple(sorted(defaults)) or ("localhost",)

    @property
    def session_cookie_name(self) -> str:
        return "__Host-creator_tools_session" if self.is_production else "creator_tools_session"

    @property
    def oauth_flow_cookie_name(self) -> str:
        return "__Host-creator_tools_oauth_flow" if self.is_production else "creator_tools_oauth_flow"

    @property
    def allowed_google_emails(self) -> frozenset[str]:
        return frozenset(email.strip().casefold() for email in self.ALLOWED_GOOGLE_EMAILS.split(",") if email.strip())

    def is_google_email_allowed(self, email: str) -> bool:
        if self.allowed_google_emails:
            return bool(email) and email.strip().casefold() in self.allowed_google_emails
        return bool(email) and not self.allowlist_required

    def get_redirect_uri(self) -> str:
        return f"{self.base_url}/api/v1/auth/callback"


settings = Settings()

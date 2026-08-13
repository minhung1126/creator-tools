import hashlib
import secrets
import warnings
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

YOUTUBE_OAUTH_SLOT_NAMES = ("primary", "secondary")


def normalize_youtube_slot(value: str) -> str:
    """Validate the small, intentionally fixed YouTube slot allowlist."""
    slot = str(value or "").strip().casefold()
    if slot not in YOUTUBE_OAUTH_SLOT_NAMES:
        raise ValueError("YouTube OAuth slot must be primary or secondary")
    return slot


@dataclass(frozen=True)
class YouTubeOAuthSlot:
    """Resolved, non-secret configuration for one YouTube OAuth slot."""

    name: str
    label: str
    client_id: str
    client_secret: str
    enabled: bool
    quota_limit: int
    safety_buffer_units: int
    uses_legacy_google_credentials: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret)

    @property
    def client_fingerprint(self) -> str | None:
        if not self.client_id:
            return None
        return hashlib.sha256(self.client_id.encode("utf-8")).hexdigest()[:16]


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

    # YouTube uses separate OAuth Web Clients from the control-panel login.
    # Primary intentionally supports a temporary fallback to the old Google
    # client so existing installations can migrate without losing tokens.
    YOUTUBE_OAUTH_PRIMARY_CLIENT_ID: str = ""
    YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET: str = ""
    YOUTUBE_OAUTH_PRIMARY_LABEL: str = "Primary"
    YOUTUBE_OAUTH_SECONDARY_ENABLED: bool = False
    YOUTUBE_OAUTH_SECONDARY_CLIENT_ID: str = ""
    YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET: str = ""
    YOUTUBE_OAUTH_SECONDARY_LABEL: str = "Secondary"
    YOUTUBE_OAUTH_DEFAULT_SLOT: str = "primary"

    SECRET_KEY: str = ""
    CREDENTIAL_ENCRYPTION_KEY: str = ""

    # YouTube quota policy values are persisted from the authenticated
    # settings page; these environment defaults are only the first-run
    # fallback and never contain secrets.
    YOUTUBE_GENERAL_QUOTA_LIMIT: int = 10_000
    YOUTUBE_QUOTA_SAFETY_BUFFER_UNITS: int = 1_000
    YOUTUBE_PRIMARY_GENERAL_QUOTA_LIMIT: int | None = None
    YOUTUBE_PRIMARY_QUOTA_SAFETY_BUFFER_UNITS: int | None = None
    YOUTUBE_SECONDARY_GENERAL_QUOTA_LIMIT: int = 10_000
    YOUTUBE_SECONDARY_QUOTA_SAFETY_BUFFER_UNITS: int = 1_000

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

        self.YOUTUBE_OAUTH_DEFAULT_SLOT = normalize_youtube_slot(self.YOUTUBE_OAUTH_DEFAULT_SLOT)
        self._validate_oauth_pair(
            "GOOGLE_CLIENT_ID",
            self.GOOGLE_CLIENT_ID,
            "GOOGLE_CLIENT_SECRET",
            self.GOOGLE_CLIENT_SECRET,
        )
        self._validate_oauth_pair(
            "YOUTUBE_OAUTH_PRIMARY_CLIENT_ID",
            self.YOUTUBE_OAUTH_PRIMARY_CLIENT_ID,
            "YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET",
            self.YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET,
        )
        self._validate_oauth_pair(
            "YOUTUBE_OAUTH_SECONDARY_CLIENT_ID",
            self.YOUTUBE_OAUTH_SECONDARY_CLIENT_ID,
            "YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET",
            self.YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET,
        )
        if self.YOUTUBE_OAUTH_SECONDARY_ENABLED and not (
            self.YOUTUBE_OAUTH_SECONDARY_CLIENT_ID and self.YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET
        ):
            raise ValueError(
                "YOUTUBE_OAUTH_SECONDARY_ENABLED=true requires both "
                "YOUTUBE_OAUTH_SECONDARY_CLIENT_ID and YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET"
            )
        if self.YOUTUBE_OAUTH_DEFAULT_SLOT == "secondary" and not self.youtube_oauth_slot("secondary").configured:
            raise ValueError("YOUTUBE_OAUTH_DEFAULT_SLOT must refer to a configured YouTube OAuth slot")

        for name, limit, buffer in (
            (
                "YOUTUBE_PRIMARY",
                self.YOUTUBE_PRIMARY_GENERAL_QUOTA_LIMIT
                if self.YOUTUBE_PRIMARY_GENERAL_QUOTA_LIMIT is not None
                else self.YOUTUBE_GENERAL_QUOTA_LIMIT,
                self.YOUTUBE_PRIMARY_QUOTA_SAFETY_BUFFER_UNITS
                if self.YOUTUBE_PRIMARY_QUOTA_SAFETY_BUFFER_UNITS is not None
                else self.YOUTUBE_QUOTA_SAFETY_BUFFER_UNITS,
            ),
            (
                "YOUTUBE_SECONDARY",
                self.YOUTUBE_SECONDARY_GENERAL_QUOTA_LIMIT,
                self.YOUTUBE_SECONDARY_QUOTA_SAFETY_BUFFER_UNITS,
            ),
        ):
            if limit <= 0:
                raise ValueError(f"{name}_GENERAL_QUOTA_LIMIT must be greater than 0")
            if buffer < 0 or buffer >= limit:
                raise ValueError(f"{name}_QUOTA_SAFETY_BUFFER_UNITS must be >= 0 and less than the quota limit")

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

    @staticmethod
    def _validate_oauth_pair(first_name: str, first_value: str, second_name: str, second_value: str) -> None:
        if bool(str(first_value or "").strip()) != bool(str(second_value or "").strip()):
            raise ValueError(f"{first_name} and {second_name} must be configured together")

    @property
    def youtube_primary_uses_legacy_credentials(self) -> bool:
        return not self.YOUTUBE_OAUTH_PRIMARY_CLIENT_ID and bool(
            self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET
        )

    def youtube_oauth_slot(self, slot: str) -> YouTubeOAuthSlot:
        slot_name = normalize_youtube_slot(slot)
        if slot_name == "primary":
            client_id = self.YOUTUBE_OAUTH_PRIMARY_CLIENT_ID or self.GOOGLE_CLIENT_ID
            client_secret = self.YOUTUBE_OAUTH_PRIMARY_CLIENT_SECRET or self.GOOGLE_CLIENT_SECRET
            limit = (
                self.YOUTUBE_PRIMARY_GENERAL_QUOTA_LIMIT
                if self.YOUTUBE_PRIMARY_GENERAL_QUOTA_LIMIT is not None
                else self.YOUTUBE_GENERAL_QUOTA_LIMIT
            )
            buffer = (
                self.YOUTUBE_PRIMARY_QUOTA_SAFETY_BUFFER_UNITS
                if self.YOUTUBE_PRIMARY_QUOTA_SAFETY_BUFFER_UNITS is not None
                else self.YOUTUBE_QUOTA_SAFETY_BUFFER_UNITS
            )
            return YouTubeOAuthSlot(
                name="primary",
                label=(self.YOUTUBE_OAUTH_PRIMARY_LABEL or "Primary").strip() or "Primary",
                client_id=client_id.strip(),
                client_secret=client_secret,
                enabled=True,
                quota_limit=int(limit),
                safety_buffer_units=int(buffer),
                uses_legacy_google_credentials=self.youtube_primary_uses_legacy_credentials,
            )

        return YouTubeOAuthSlot(
            name="secondary",
            label=(self.YOUTUBE_OAUTH_SECONDARY_LABEL or "Secondary").strip() or "Secondary",
            client_id=self.YOUTUBE_OAUTH_SECONDARY_CLIENT_ID.strip(),
            client_secret=self.YOUTUBE_OAUTH_SECONDARY_CLIENT_SECRET,
            enabled=bool(self.YOUTUBE_OAUTH_SECONDARY_ENABLED),
            quota_limit=int(self.YOUTUBE_SECONDARY_GENERAL_QUOTA_LIMIT),
            safety_buffer_units=int(self.YOUTUBE_SECONDARY_QUOTA_SAFETY_BUFFER_UNITS),
        )

    @property
    def youtube_oauth_slots(self) -> dict[str, YouTubeOAuthSlot]:
        return {slot: self.youtube_oauth_slot(slot) for slot in YOUTUBE_OAUTH_SLOT_NAMES}

    @property
    def youtube_default_slot(self) -> str:
        return self.YOUTUBE_OAUTH_DEFAULT_SLOT

    def youtube_oauth_warnings(self) -> list[str]:
        warnings_list: list[str] = []
        if self.youtube_primary_uses_legacy_credentials:
            warnings_list.append(
                "YouTube primary OAuth is using the legacy GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET fallback; "
                "configure YOUTUBE_OAUTH_PRIMARY_* before removing the legacy client."
            )
        if not self.youtube_oauth_slot("primary").configured:
            warnings_list.append("YouTube primary OAuth credentials are not configured")
        if self.YOUTUBE_OAUTH_SECONDARY_ENABLED and not self.youtube_oauth_slot("secondary").configured:
            warnings_list.append("YouTube secondary OAuth credentials are not configured")
        return warnings_list

    def is_google_email_allowed(self, email: str) -> bool:
        if self.allowed_google_emails:
            return bool(email) and email.strip().casefold() in self.allowed_google_emails
        return bool(email) and not self.allowlist_required

    def get_redirect_uri(self) -> str:
        return f"{self.base_url}/api/v1/auth/callback"


settings = Settings()

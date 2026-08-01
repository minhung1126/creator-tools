import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    HOST: str = "localhost"
    PORT: int = 8000

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    SECRET_KEY: str = "creator-tools-super-secret-key-change-in-production-2026"
    CREDENTIAL_ENCRYPTION_KEY: str = ""

    # Default Resource Configurations (can be overridden by runtime_config.json)
    DEFAULT_SPREADSHEET_ID: str = ""
    DEFAULT_PLAYLIST_ID: str = ""
    DEFAULT_DRIVE_FOLDER_ID: str = ""

    # Instagram API with Instagram Login
    INSTAGRAM_APP_ID: str = ""
    INSTAGRAM_APP_SECRET: str = ""
    INSTAGRAM_REDIRECT_URI: str = ""
    INSTAGRAM_API_VERSION: str = "v25.0"

    # Legacy names kept for existing deployments. New installs should use INSTAGRAM_*.
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_ACCESS_TOKEN: str = ""

    # Cloudflare R2 defaults. UI values can override non-secret fields.
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_BASE_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        """Determine if running in production based on HOST value."""
        return self.HOST not in ("localhost", "127.0.0.1", "0.0.0.0")

    @property
    def scheme(self) -> str:
        return "https" if self.is_production else "http"

    @property
    def base_url(self) -> str:
        """Full backend base URL."""
        if self.is_production:
            return f"{self.scheme}://{self.HOST}"
        return f"{self.scheme}://{self.HOST}:{self.PORT}"

    @property
    def frontend_url(self) -> str:
        """Frontend URL — same origin in production, port 3000 in dev."""
        if self.is_production:
            return self.base_url
        return f"http://{self.HOST}:3000"

    @property
    def instagram_app_id(self) -> str:
        return self.INSTAGRAM_APP_ID or self.META_APP_ID

    @property
    def instagram_app_secret(self) -> str:
        return self.INSTAGRAM_APP_SECRET or self.META_APP_SECRET

    def get_redirect_uri(self) -> str:
        return f"{self.base_url}/api/v1/auth/callback"

    def get_instagram_redirect_uri(self) -> str:
        return self.INSTAGRAM_REDIRECT_URI or f"{self.base_url}/api/v1/instagram/auth/callback"


settings = Settings()

# Startup warning for default SECRET_KEY
if settings.SECRET_KEY == "creator-tools-super-secret-key-change-in-production-2026":
    warnings.warn(
        "⚠️  Using default SECRET_KEY! Please set a unique SECRET_KEY in .env for production.",
        stacklevel=2,
    )

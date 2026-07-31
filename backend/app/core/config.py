import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    HOST: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    
    SECRET_KEY: str = "creator-tools-super-secret-key-change-in-production-2026"
    
    # Default Resource Configurations
    DEFAULT_SPREADSHEET_ID: str = "1xsxDJ80-TOQs3d3ecHALEbyMlxxEkwXNjHaW7yA8wVs"
    DEFAULT_PLAYLIST_ID: str = "PLhu1MP3FpZmHar5qPZJkl6zCqXzddF4nC"
    DEFAULT_DRIVE_FOLDER_ID: str = ""
    
    # Future Extensibility: Meta API Settings
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_ACCESS_TOKEN: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_redirect_uri(self) -> str:
        if self.GOOGLE_REDIRECT_URI:
            return self.GOOGLE_REDIRECT_URI
        clean_host = self.HOST.rstrip("/")
        return f"{clean_host}/api/v1/auth/callback"

settings = Settings()

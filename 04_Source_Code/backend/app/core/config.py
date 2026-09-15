from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str
    jwt_secret: str = Field(min_length=32)
    app_origin: str = "http://127.0.0.1:3000"
    trusted_hosts: str = "127.0.0.1,localhost,testserver,10.0.2.2"
    cookie_secure: bool = False
    upload_dir: Path = ROOT / ".local" / "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024
    session_minutes: int = 120
    login_attempts: int = 20
    extraction_python: Path = ROOT / ".local/ocr-venv/Scripts/python.exe"
    extraction_timeout_seconds: int = Field(default=420, ge=10, le=600)

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

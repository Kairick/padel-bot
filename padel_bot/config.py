from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from padel_bot.reservio.models import Venue

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Asia/Tbilisi")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: SecretStr
    cache_ttl_seconds: int = 60
    log_level: str = "INFO"
    venues_file: Path = ROOT / "venues.yaml"
    reservio_api_url: str = "https://api.reservio.com"
    stats_db_path: Path = ROOT / "data" / "stats.sqlite3"
    # Telegram user ids allowed to use /stats, comma separated in env: ADMIN_IDS=123,456
    admin_ids: Annotated[list[int], NoDecode] = []

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        return value


class VenuesFile(BaseModel):
    venues: list[Venue]


def load_venues(path: Path) -> list[Venue]:
    with path.open() as f:
        return VenuesFile.model_validate(yaml.safe_load(f)).venues


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

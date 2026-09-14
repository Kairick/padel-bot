from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

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


class VenuesFile(BaseModel):
    venues: list[Venue]


def load_venues(path: Path) -> list[Venue]:
    with path.open() as f:
        return VenuesFile.model_validate(yaml.safe_load(f)).venues


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

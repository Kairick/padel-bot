from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ServiceConfig(BaseModel):
    id: str
    price: Decimal


class CourtConfig(BaseModel):
    name: str
    group: str | None = None
    services: list[ServiceConfig]


class Venue(BaseModel):
    key: str
    name: str
    # Shown on the club's header row of the day view, where a long name only wastes width.
    short_name: str | None = None
    subdomain: str
    business_id: str
    courts: list[CourtConfig]

    @property
    def short_label(self) -> str:
        return self.short_name or self.name

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.reservio.com"


@dataclass(frozen=True, slots=True)
class RawSlot:
    """A slot as returned by Reservio for a single service."""

    start: datetime
    end: datetime
    resource_id: str | None


@dataclass(frozen=True, slots=True)
class CourtSlot:
    """A free slot on a concrete court, ready for display."""

    venue: Venue
    court: CourtConfig
    service_id: str
    resource_id: str | None
    start: datetime
    end: datetime
    price: Decimal

    @property
    def booking_url(self) -> str:
        url = f"{self.venue.base_url}/booking?step=1&serviceId={self.service_id}"
        if self.resource_id:
            url = (
                f"{self.venue.base_url}/booking?step=2"
                f"&serviceId={self.service_id}&resourceId={self.resource_id}"
            )
        return url

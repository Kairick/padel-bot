import asyncio
from datetime import date, datetime
from decimal import Decimal

import pytest

from padel_bot.config import TZ
from padel_bot.reservio.client import ReservioError
from padel_bot.reservio.models import CourtConfig, RawSlot, ServiceConfig, Venue


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


class FakeClient:
    def __init__(self, data: dict[str, list[RawSlot]], failing: set[str] | None = None) -> None:
        self.data = data
        self.failing = failing or set()
        self.calls: list[tuple[str, date, date]] = []

    async def get_slots(self, business_id: str, service_id: str, date_from: date, date_to: date):
        self.calls.append((service_id, date_from, date_to))
        await asyncio.sleep(0.01)
        if service_id in self.failing:
            raise ReservioError("boom")
        return self.data.get(service_id, [])


@pytest.fixture
def venues() -> list[Venue]:
    return [
        Venue(
            key="pp",
            name="Padel Port",
            subdomain="pp",
            business_id="b-pp",
            courts=[
                CourtConfig(name="Padel 1", services=[ServiceConfig(id="pp1", price=Decimal(80))]),
                CourtConfig(name="Padel 2", services=[ServiceConfig(id="pp2", price=Decimal(80))]),
            ],
        ),
        Venue(
            key="gp",
            name="Grand Padel",
            subdomain="gp",
            business_id="b-gp",
            courts=[
                CourtConfig(
                    name="Court A",
                    group="Road side",
                    services=[
                        ServiceConfig(id="gpa-day", price=Decimal(65)),
                        ServiceConfig(id="gpa-eve", price=Decimal(80)),
                    ],
                )
            ],
        ),
    ]


def slot(start: str, resource: str = "r1") -> RawSlot:
    s = dt(start)
    return RawSlot(start=s, end=s.replace(minute=59), resource_id=resource)

import asyncio
from datetime import date, datetime
from decimal import Decimal

import pytest

from padel_bot.domain import TZ
from padel_bot.reservio.client import ReservioError
from padel_bot.reservio.models import CourtConfig, RawSlot, ServiceConfig, Venue


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


class FakeClient:
    def __init__(
        self,
        data: dict[str, list[RawSlot]],
        failing: set[str] | None = None,
        checkout_failing: set[str] | None = None,
    ) -> None:
        self.data = data
        self.failing = failing or set()
        self.checkout_failing = checkout_failing or set()
        self.checkout_delay = 0.0
        self.calls: list[tuple[str, date, date]] = []
        self.checkout_calls: list[str] = []

    async def create_checkout_url(
        self,
        subdomain: str,
        business_id: str,
        service_id: str,
        resource_id: str | None,
        start: datetime,
    ) -> str:
        self.checkout_calls.append(service_id)
        await asyncio.sleep(self.checkout_delay)
        if service_id in self.checkout_failing:
            raise ReservioError("no checkout")
        n = len(self.checkout_calls)
        return f"https://{subdomain}.reservio.com/order?orderId=o-{service_id}-{n}&what=time"

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

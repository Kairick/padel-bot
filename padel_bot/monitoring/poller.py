"""Background polling of Reservio for subscriptions: schedule, requests, notifications."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

from padel_bot.bot.formatting import render_notification
from padel_bot.bot.keyboards import notification_keyboard
from padel_bot.config import TZ
from padel_bot.monitoring.matcher import CyclePlan, SubscriptionPlan, plan_cycle
from padel_bot.monitoring.models import MatchKey
from padel_bot.monitoring.store import SubscriptionStore
from padel_bot.reservio.client import ReservioClient, ReservioError
from padel_bot.reservio.models import RawSlot, Venue
from padel_bot.reservio.service import current_play_day

log = logging.getLogger(__name__)

# Reservio's window is about a week; one request per service covers it with a margin.
LOOKAHEAD_DAYS = 8
JITTER_SECONDS = 60
MAX_BACKOFF_SECONDS = 3600
# No polling at night. Polling stops ten minutes before midnight so that the last cycle's
# notifications don't arrive after 00:00.
QUIET_FROM = time(23, 50)
QUIET_UNTIL = time(7, 50)
MAX_TIMES_PER_MESSAGE = 20
# Errors after which the chat can't receive messages anymore.
GONE_CHAT_ERRORS = ("chat not found", "user is deactivated", "bot was blocked")


def quiet_seconds(now: datetime) -> float:
    """Seconds left until polling may resume, 0 outside quiet hours."""
    local = now.astimezone(TZ)
    if QUIET_UNTIL <= local.time() < QUIET_FROM:
        return 0.0
    wake = datetime.combine(local.date(), QUIET_UNTIL, TZ)
    if local.time() >= QUIET_FROM:
        wake += timedelta(days=1)
    return (wake - local).total_seconds()


def next_delay(interval: float, failures: int, retry_after: float | None) -> float:
    """Normal interval, doubled per failed cycle up to an hour, never shorter than Retry-After."""
    delay = interval
    if failures:
        delay = min(interval * 2 ** min(failures, 10), max(interval, MAX_BACKOFF_SECONDS))
    return max(delay, retry_after or 0.0)


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    ok: bool
    retry_after: float | None = None
    notified_chats: int = 0


class Poller:
    def __init__(
        self,
        bot: Bot,
        client: ReservioClient,
        venues: list[Venue],
        store: SubscriptionStore,
        interval_seconds: float = 600,
        *,
        jitter_seconds: float = JITTER_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(TZ),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bot = bot
        self._client = client
        self._venues = venues
        self._store = store
        self._interval = interval_seconds
        self._jitter = jitter_seconds
        self._clock = clock
        self._sleep = sleep

    async def run(self) -> None:
        failures = 0
        while True:
            if (wait := quiet_seconds(self._clock())) > 0:
                log.info("monitor: quiet hours, sleeping %.0f s", wait)
                await self._sleep(wait)
                continue
            try:
                outcome = await self.run_cycle()
            except Exception:
                log.exception("monitor: cycle failed")
                outcome = CycleOutcome(ok=False)
            failures = 0 if outcome.ok else failures + 1
            delay = next_delay(self._interval, failures, outcome.retry_after)
            await self._sleep(delay + random.uniform(0, self._jitter))

    async def run_cycle(self) -> CycleOutcome:
        cycle_started_at = self._clock()
        self._store.cleanup(
            cycle_started_at,
            venue_keys={v.key for v in self._venues},
            service_ids={s.id for v in self._venues for c in v.courts for s in c.services},
        )
        if not self._store.has_subscriptions():
            return CycleOutcome(ok=True)

        results = await self._fetch(cycle_started_at)
        errors = [r for r in results.values() if isinstance(r, BaseException)]
        for error in errors:
            log.warning("monitor: fetch failed: %s", error)
        retry_after = max(
            (e.retry_after for e in errors if isinstance(e, ReservioError) and e.retry_after),
            default=None,
        )
        if results and len(errors) == len(results):
            return CycleOutcome(ok=False, retry_after=retry_after)

        # Subscriptions are read after the responses: a change made during the requests has
        # changed_at later than cycle_started_at and gets re-baselined, not notified.
        now = self._clock()
        plan = plan_cycle(
            venues=self._venues,
            results=results,
            subscriptions=self._store.all(),
            known=self._store.known_matches(),
            states=self._store.poll_state(),
            cycle_started_at=cycle_started_at,
            now=now,
        )
        self._store.apply_cycle(plan, now)
        notified = await self._notify(plan)
        log.info(
            "monitor: cycle done, %d services, %d failed, %d clubs ok, %d chats notified",
            len(results),
            len(errors),
            len(plan.ok_venues),
            notified,
        )
        return CycleOutcome(ok=True, retry_after=retry_after, notified_chats=notified)

    async def _fetch(self, now: datetime) -> dict[str, list[RawSlot] | BaseException]:
        day_from = current_play_day(now)
        day_to = day_from + timedelta(days=LOOKAHEAD_DAYS)
        jobs = [
            (venue.business_id, service.id)
            for venue in self._venues
            for court in venue.courts
            for service in court.services
        ]
        responses = await asyncio.gather(
            *(self._client.get_slots(b, s, day_from, day_to) for b, s in jobs),
            return_exceptions=True,
        )
        return {service_id: r for (_, service_id), r in zip(jobs, responses, strict=True)}

    async def _notify(self, plan: CyclePlan) -> int:
        by_chat: dict[int, list[SubscriptionPlan]] = {}
        for sp in plan.subscriptions:
            if sp.send:
                by_chat.setdefault(sp.subscription.chat_id, []).append(sp)

        notified = 0
        for chat_id, plans in by_chat.items():
            # The user may have deleted or changed a subscription while the cycle was running.
            live = [sp for sp in plans if self._store.is_unchanged(sp.subscription)]
            if not live:
                continue
            lang = max(live, key=lambda sp: sp.subscription.changed_at).subscription.lang
            keys = {key for sp in live for key in sp.send}
            text, markup = self.render(keys, plan, lang)
            if await self._send(chat_id, text, markup):
                self._store.mark_notified(
                    [(sp.subscription, sp.send) for sp in live], self._clock()
                )
                notified += 1
        return notified

    def render(
        self, keys: set[MatchKey], plan: CyclePlan, lang
    ) -> tuple[str, InlineKeyboardMarkup]:
        order = {v.key: i for i, v in enumerate(self._venues)}
        venue_by_key = {v.key: v for v in self._venues}
        ordered = sorted(
            keys, key=lambda k: (current_play_day(k[1]), k[1], order.get(k[0], len(order)))
        )
        shown = ordered[:MAX_TIMES_PER_MESSAGE]
        starts = [
            (venue_by_key[venue_key], current_play_day(start), start, plan.free[(venue_key, start)])
            for venue_key, start in shown
        ]
        # The text is grouped by day and club, buttons follow the same order.
        starts.sort(key=lambda item: (item[1], order[item[0].key], item[2]))
        text = render_notification(starts, self._venues, len(ordered) - len(shown), lang)
        markup = notification_keyboard(
            [(venue, day, start) for venue, day, start, _ in starts],
            self._venues,
            current_play_day(self._clock()),
            lang,
        )
        return text, markup

    async def _send(self, chat_id: int, text: str, markup: InlineKeyboardMarkup) -> bool:
        for attempt in range(2):
            try:
                await self._bot.send_message(chat_id, text, reply_markup=markup)
                return True
            except TelegramRetryAfter as e:
                if attempt:
                    log.warning("monitor: still rate limited by Telegram, giving up: %s", e)
                    return False
                await self._sleep(e.retry_after)
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                if isinstance(e, TelegramForbiddenError) or any(
                    marker in str(e).lower() for marker in GONE_CHAT_ERRORS
                ):
                    deleted = self._store.delete_chat(chat_id)
                    log.info("monitor: chat unreachable, deleted %d subscriptions: %s", deleted, e)
                else:
                    log.warning("monitor: notification rejected: %s", e)
                return False
            except TelegramAPIError as e:
                log.warning("monitor: notification failed: %s", e)
                return False
        return False

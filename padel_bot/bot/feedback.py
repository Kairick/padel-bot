"""/feedback: a user's message is forwarded to the admins together with who sent it.

`/feedback text` sends right away. Bare `/feedback` waits for the next message (text,
screenshot, anything) for a while. An album arrives as several messages: the first one
decides, the rest follow it.

Updates are handled as concurrent tasks, and aiogram runs sync filters in threads, so
two messages can pass the filters together. Every decision is therefore made in handler
code before its first await. The waits live in process memory, a restart drops them.
"""

import asyncio
import logging
from html import escape

from aiogram import Bot, F
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyParameters
from cachetools import TTLCache

from padel_bot.bot.common import lang_of, private_router
from padel_bot.bot.i18n import t
from padel_bot.bot.throttle import RateLimiter
from padel_bot.stats import Stats

log = logging.getLogger(__name__)

router = private_router("feedback")

# Other commands don't cancel the wait, so a forgotten /feedback must not swallow
# a message typed much later.
WAIT_SECONDS = 600

# Users who sent bare /feedback: their next message is the feedback.
waiting: TTLCache[int, bool] = TTLCache(maxsize=10_000, ttl=WAIT_SECONDS)
# Album id -> whether its first part was delivered. Telegram sends all parts at once.
albums: TTLCache[str, asyncio.Future[bool]] = TTLCache(maxsize=1_000, ttl=60)

# The captioned album part with /feedback may reach its handler after the other parts.
ALBUM_GRACE_SECONDS = 1.0

# Any message but a command: a screenshot has no text and still counts.
NOT_COMMAND = ~F.text.startswith("/")


def sender_line(message: Message) -> str:
    user = message.from_user
    assert user is not None
    parts = [f"💬 <b>Фидбек</b> · id <code>{user.id}</code>"]
    if user.username:
        parts.append(f"@{escape(user.username)}")
    parts.append(escape(user.full_name))
    if user.language_code:
        parts.append(escape(user.language_code))
    return " · ".join(parts)


async def deliver(
    message: Message, bot: Bot, admin_ids: frozenset[int], with_sender: bool = True
) -> bool:
    """Forward to every admin; True if at least one got it."""
    delivered = False
    for admin_id in admin_ids:
        try:
            forwarded = await bot.forward_message(admin_id, message.chat.id, message.message_id)
        except TelegramAPIError as e:
            # Usually the admin never opened the bot, so it can't write to them.
            log.warning("feedback not delivered to admin %s: %s", admin_id, e)
            continue
        delivered = True
        if not with_sender:
            continue
        try:
            await bot.send_message(
                admin_id,
                sender_line(message),
                reply_parameters=ReplyParameters(message_id=forwarded.message_id),
            )
        except TelegramAPIError as e:
            log.warning("feedback sender line not sent to admin %s: %s", admin_id, e)
    return delivered


async def follow_album(message: Message, bot: Bot, admin_ids: frozenset[int]) -> bool:
    """Handle a part of an album that is already feedback; False if it isn't one."""
    first = albums.get(message.media_group_id) if message.media_group_id else None
    if first is None:
        return False
    # Shielded: a cancelled follower must not cancel the result the others wait for.
    if await asyncio.shield(first):
        await deliver(message, bot, admin_ids, with_sender=False)
    return True


async def submit(
    message: Message,
    bot: Bot,
    admin_ids: frozenset[int],
    stats: Stats,
    feedback_limiter: RateLimiter,
) -> None:
    """Send the message as feedback. The caller must not await anything before this."""
    user = message.from_user
    assert user is not None
    lang = lang_of(user)
    result: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    if message.media_group_id is not None:
        albums[message.media_group_id] = result
    delivered = False
    try:
        if not feedback_limiter.allow(user.id):
            await message.answer(t(lang, "feedback_too_many"))
            return
        delivered = await deliver(message, bot, admin_ids)
    finally:
        # The other album parts wait for this.
        if not result.done():
            result.set_result(delivered)
    if not delivered:
        await message.answer(t(lang, "feedback_failed"))
        return
    stats.track_event("feedback")
    await message.answer(t(lang, "feedback_thanks"))


@router.message(Command("feedback"))
async def cmd_feedback(
    message: Message,
    command: CommandObject,
    bot: Bot,
    admin_ids: frozenset[int],
    stats: Stats,
    feedback_limiter: RateLimiter,
) -> None:
    user = message.from_user
    if user is None:
        return
    waiting.pop(user.id, None)
    if not admin_ids:
        await message.answer(t(lang_of(user), "feedback_failed"))
        return
    # A screenshot captioned just "/feedback" is the feedback itself.
    if command.args or message.content_type != ContentType.TEXT:
        await submit(message, bot, admin_ids, stats, feedback_limiter)
        return
    waiting[user.id] = True
    await message.answer(t(lang_of(user), "feedback_prompt"))


@router.message(NOT_COMMAND)
async def on_message(
    message: Message,
    bot: Bot,
    admin_ids: frozenset[int],
    stats: Stats,
    feedback_limiter: RateLimiter,
) -> None:
    user = message.from_user
    if user is None or await follow_album(message, bot, admin_ids):
        return
    if waiting.pop(user.id, None) is not None:
        await submit(message, bot, admin_ids, stats, feedback_limiter)
        return
    if message.media_group_id is not None:
        await asyncio.sleep(ALBUM_GRACE_SECONDS)
        await follow_album(message, bot, admin_ids)

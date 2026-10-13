from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import Message

logger = logging.getLogger(__name__)

_ATTEMPTS = 3
_REQUEST_TIMEOUT = 10
_BASE_DELAY = 0.5

_RETRYABLE = (
    TelegramNetworkError,
    TelegramServerError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)


async def answer(message: Message, text: str, **kwargs: Any) -> Message:
    """Отправка через message.answer + Bot(..., request_timeout=...) с ретраями.

    request_timeout — аргумент Bot.__call__/Bot.send_message, не Message.answer.
    """
    if message.bot is None:
        raise RuntimeError("У message нет bot — нельзя отправить ответ")

    request_timeout = int(kwargs.pop("request_timeout", _REQUEST_TIMEOUT))
    last_error: BaseException | None = None

    for attempt in range(1, _ATTEMPTS + 1):
        try:
            method = message.answer(text, **kwargs)
            return await message.bot(method, request_timeout=request_timeout)
        except TelegramRetryAfter as exc:
            last_error = exc
            delay = float(exc.retry_after) + 0.1
            logger.info(
                "message.answer flood-wait attempt=%s/%s sleep=%.1fs",
                attempt,
                _ATTEMPTS,
                delay,
            )
        except _RETRYABLE as exc:
            last_error = exc
            delay = _BASE_DELAY * attempt
            logger.info(
                "message.answer failed attempt=%s/%s: %s; retry in %.1fs",
                attempt,
                _ATTEMPTS,
                exc,
                delay,
            )

        if attempt >= _ATTEMPTS:
            break
        await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error

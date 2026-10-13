from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any

from aiogram.types import Update

from bot.factory import get_runtime

logger = logging.getLogger(__name__)

_OK = {"statusCode": 200, "body": "ok"}


def _parse_update(event: Any) -> dict[str, Any] | None:
    """Единственный контракт: тело async-invoke от proxy (Telegram update JSON)."""
    payload: Any = event
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("event должен быть JSON-объектом Telegram update")
    if "update_id" not in payload:
        raise ValueError("в event нет update_id")
    return payload


async def handler(event: Any, context: Any) -> dict[str, Any]:
    started_at = perf_counter()
    logger.info("Core: получен event type=%s", type(event).__name__)

    try:
        payload = _parse_update(event)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        logger.exception("Отклонён некорректный update")
        return {"statusCode": 400, "body": "bad request"}

    if payload is None:
        logger.info(
            "Core: пустой update, duration_ms=%.1f",
            (perf_counter() - started_at) * 1_000,
        )
        return _OK

    update_id = payload.get("update_id")
    logger.info("Core: update_id=%s", update_id)

    runtime_started_at = perf_counter()
    bot, dispatcher = await get_runtime()
    logger.info(
        "Runtime готов, duration_ms=%.1f",
        (perf_counter() - runtime_started_at) * 1_000,
    )

    update = Update.model_validate(payload, context={"bot": bot})
    dispatch_started_at = perf_counter()
    await dispatcher.feed_update(bot, update)
    logger.info(
        "Update обработан: update_id=%s, dispatch_ms=%.1f, total_ms=%.1f",
        update.update_id,
        (perf_counter() - dispatch_started_at) * 1_000,
        (perf_counter() - started_at) * 1_000,
    )
    return _OK

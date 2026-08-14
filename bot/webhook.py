from __future__ import annotations

import base64
import json
import logging
from typing import Any

from aiogram.types import Update

from bot.config import Settings
from bot.factory import get_runtime, get_settings

logger = logging.getLogger(__name__)

_OK = {"statusCode": 200, "body": "ok"}


def _headers(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("headers") or {}
    return {str(key).lower(): str(value) for key, value in raw.items()}


def _extract_update(event: dict[str, Any]) -> dict[str, Any] | None:
    if "update_id" in event:
        return event

    body = event.get("body")
    if body in (None, ""):
        return None
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, dict):
        return body
    parsed = json.loads(body)
    if isinstance(parsed, dict):
        return parsed
    return None


def _is_secret_valid(event: dict[str, Any], settings: Settings) -> bool:
    if not settings.webhook_secret:
        return True
    token = _headers(event).get("x-telegram-bot-api-secret-token")
    return token == settings.webhook_secret


async def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    method = str(event.get("httpMethod") or "POST").upper()
    if method in {"GET", "HEAD"}:
        return _OK
    if not _is_secret_valid(event, settings):
        logger.warning("Отклонён запрос с неверным webhook secret")
        return {"statusCode": 403, "body": "forbidden"}

    try:
        payload = _extract_update(event)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        logger.exception("Некорректное тело webhook")
        return {"statusCode": 400, "body": "bad request"}

    if payload is None:
        return _OK

    bot, dispatcher = await get_runtime()
    update = Update.model_validate(payload, context={"bot": bot})
    await dispatcher.feed_update(bot, update)
    return _OK

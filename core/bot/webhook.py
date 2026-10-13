from __future__ import annotations

import json
import logging
import secrets
from time import perf_counter
from typing import Any

from aiohttp import web
from aiogram.types import Update

from bot.config import Settings
from bot.factory import get_runtime, get_settings

logger = logging.getLogger(__name__)


async def _process_update(payload: dict[str, Any]) -> None:
    started_at = perf_counter()
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


async def handle_request(request: web.Request) -> web.Response:
    """Принимает update и обрабатывает его (ответы пользователю — через Bot API).

    Публичный 200 для Telegram отдаёт nginx (mirror). Ответ этого хендлера
    видит только nginx и отбрасывает; на скорость webhook он не влияет.
    """
    started_at = perf_counter()
    logger.info("Core: method=%s path=%s", request.method, request.path)

    if request.method in {"GET", "HEAD"}:
        return web.Response(text="ok")
    if request.method != "POST":
        return web.Response(status=405, text="method not allowed")

    settings: Settings = request.app["settings"]
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(token, settings.webhook_secret):
        logger.info("Отклонён запрос с неверным webhook secret")
        return web.Response(status=403, text="forbidden")

    try:
        body = await request.read()
    except Exception:
        logger.exception("Не удалось прочитать тело запроса")
        return web.Response(status=400, text="bad request")

    if not body:
        logger.info(
            "Core: пустой update, duration_ms=%.1f",
            (perf_counter() - started_at) * 1_000,
        )
        return web.Response(text="ok")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.exception("Отклонён некорректный update")
        return web.Response(status=400, text="bad request")

    if not isinstance(payload, dict) or "update_id" not in payload:
        logger.info("Отклонён запрос без update_id")
        return web.Response(status=400, text="bad request")

    try:
        await _process_update(payload)
    except Exception:
        logger.exception("Ошибка обработки update_id=%s", payload.get("update_id"))
        return web.Response(status=500, text="error")

    return web.Response(text="ok")


async def install_webhook(settings: Settings) -> None:
    """Зарегистрировать webhook в Telegram (setWebhook)."""
    settings.require_webhook_secret()
    if not settings.webhook_url:
        raise RuntimeError("Не задана переменная окружения WEBHOOK_URL")

    bot, _dispatcher = await get_runtime()
    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.webhook_secret,
        drop_pending_updates=True,
    )
    logger.info("Webhook установлен: %s", settings.webhook_url)


async def remove_webhook() -> None:
    """Снять webhook в Telegram (deleteWebhook)."""
    bot, _dispatcher = await get_runtime()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook удалён")


async def create_app() -> web.Application:
    settings = get_settings()
    settings.require_webhook_secret()
    if not settings.webhook_url:
        raise RuntimeError("Не задана переменная окружения WEBHOOK_URL")
    await get_runtime()

    app = web.Application()
    app["settings"] = settings
    app.router.add_route("*", settings.webhook_path, handle_request)
    return app

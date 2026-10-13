from __future__ import annotations

import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from bot.cardio import router as cardio_router
from bot.climb import router as climb_router
from bot.config import Settings
from bot.db import YdbClient, YdbStorage
from bot.delete import router as delete_router
from bot.handlers import router as start_router
from bot.last import router as last_router
from bot.middlewares import DbMiddleware, DeleteReadyOnCommandMiddleware

logger = logging.getLogger(__name__)

_settings: Settings | None = None
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_ydb: YdbClient | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


async def get_runtime() -> tuple[Bot, Dispatcher]:
    global _bot, _dispatcher, _ydb
    if _bot is not None and _dispatcher is not None:
        return _bot, _dispatcher

    settings = get_settings()
    _ydb = YdbClient(settings)
    await _ydb.connect()

    api = TelegramAPIServer.from_base(settings.telegram_api_base)
    session = AiohttpSession(api=api)
    session._connector_init["family"] = socket.AF_INET
    _bot = Bot(token=settings.bot_token, session=session)
    logger.info("Bot API base: %s", settings.telegram_api_base)
    _dispatcher = Dispatcher(storage=YdbStorage(_ydb))
    _dispatcher.update.middleware(DbMiddleware(_ydb))
    _dispatcher.message.middleware(DeleteReadyOnCommandMiddleware())
    _dispatcher.include_router(climb_router)
    _dispatcher.include_router(cardio_router)
    _dispatcher.include_router(last_router)
    _dispatcher.include_router(delete_router)
    _dispatcher.include_router(start_router)
    logger.info("Бот и диспетчер инициализированы")
    return _bot, _dispatcher


async def close_runtime() -> None:
    global _bot, _dispatcher, _ydb
    if _dispatcher is not None:
        await _dispatcher.storage.close()
        _dispatcher = None
    if _bot is not None:
        await _bot.session.close()
        _bot = None
    if _ydb is not None:
        await _ydb.close()
        _ydb = None

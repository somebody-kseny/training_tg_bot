from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.db import UsersRepo, YdbClient


class DbMiddleware(BaseMiddleware):
    def __init__(self, ydb_client: YdbClient) -> None:
        self._ydb = ydb_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["users"] = UsersRepo(self._ydb)
        return await handler(event, data)

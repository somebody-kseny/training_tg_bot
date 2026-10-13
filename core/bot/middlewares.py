from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from bot.db import CardioRepo, ClimbingRepo, UsersRepo, YdbClient
from bot.ready import delete_ready_prompt


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
        data["climbing"] = ClimbingRepo(self._ydb)
        data["cardio"] = CardioRepo(self._ydb)
        return await handler(event, data)


class DeleteReadyOnCommandMiddleware(BaseMiddleware):
    """Удаляет сообщение «бот готов» при любой новой команде пользователя."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and (event.text or "").startswith("/"):
            state = data.get("state")
            if isinstance(state, FSMContext):
                await delete_ready_prompt(event, state)
        return await handler(event, data)

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import ydb
import ydb.aio
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import (
    BaseStorage,
    DefaultKeyBuilder,
    KeyBuilder,
    StateType,
    StorageKey,
)

from bot.config import Settings

logger = logging.getLogger(__name__)


def _credentials() -> Any:
    if os.getenv("YDB_ANONYMOUS_CREDENTIALS") == "1":
        return ydb.AnonymousCredentials()
    token = os.getenv("YDB_ACCESS_TOKEN_CREDENTIALS")
    if token:
        return ydb.AccessTokenCredentials(token)
    sa_file = os.getenv("YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS")
    if sa_file:
        import ydb.iam

        return ydb.iam.ServiceAccountCredentials.from_file(sa_file)
    import ydb.iam

    return ydb.iam.MetadataUrlCredentials()


@dataclass(slots=True)
class User:
    telegram_id: int
    username: str | None
    name: str | None


class YdbClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._driver: ydb.aio.Driver | None = None
        self._pool: ydb.aio.QuerySessionPool | None = None

    @property
    def pool(self) -> ydb.aio.QuerySessionPool:
        if self._pool is None:
            raise RuntimeError("YDB-клиент ещё не подключён")
        return self._pool

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._driver = ydb.aio.Driver(
            endpoint=self._settings.ydb_endpoint,
            database=self._settings.ydb_database,
            credentials=_credentials(),
        )
        await self._driver.wait(timeout=10, fail_fast=True)
        self._pool = ydb.aio.QuerySessionPool(self._driver)
        logger.info("Подключение к YDB установлено")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.stop()
            self._pool = None
        if self._driver is not None:
            await self._driver.stop()
            self._driver = None


class UsersRepo:
    def __init__(self, ydb_client: YdbClient) -> None:
        self._ydb = ydb_client

    async def upsert(self, telegram_id: int, username: str | None, name: str) -> None:
        params = {
            "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
            "$username": (username, ydb.OptionalType(ydb.PrimitiveType.Utf8)),
            "$name": (name, ydb.PrimitiveType.Utf8),
        }
        retry = ydb.RetrySettings(idempotent=True)
        await self._ydb.pool.execute_with_retries(
            """
            DECLARE $telegramId AS Int64;
            DECLARE $username AS Optional<Utf8>;
            DECLARE $name AS Utf8;

            UPSERT INTO users (telegram_id, username, name, updated_at)
            VALUES ($telegramId, $username, $name, CurrentUtcTimestamp());
            """,
            params,
            retry_settings=retry,
        )
        await self._ydb.pool.execute_with_retries(
            """
            DECLARE $telegramId AS Int64;

            UPDATE users
            SET created_at = CurrentUtcTimestamp()
            WHERE telegram_id = $telegramId AND created_at IS NULL;
            """,
            {"$telegramId": params["$telegramId"]},
            retry_settings=retry,
        )

    async def get(self, telegram_id: int) -> User | None:
        result_sets = await self._ydb.pool.execute_with_retries(
            """
            DECLARE $telegramId AS Int64;

            SELECT telegram_id, username, name
            FROM users
            WHERE telegram_id = $telegramId;
            """,
            {"$telegramId": (telegram_id, ydb.PrimitiveType.Int64)},
            retry_settings=ydb.RetrySettings(idempotent=True),
        )
        rows = result_sets[0].rows
        if not rows:
            return None
        row = rows[0]
        return User(
            telegram_id=int(row.telegram_id),
            username=row.username,
            name=row.name,
        )


class YdbStorage(BaseStorage):
    def __init__(
        self,
        ydb_client: YdbClient,
        key_builder: KeyBuilder | None = None,
    ) -> None:
        self._ydb = ydb_client
        self._key_builder = key_builder or DefaultKeyBuilder(with_bot_id=True, with_destiny=True)

    def _key(self, key: StorageKey) -> str:
        return self._key_builder.build(key)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self._ydb.pool.execute_with_retries(
            """
            DECLARE $key AS Utf8;
            DECLARE $state AS Optional<Utf8>;

            UPSERT INTO fsm_storage (key, state)
            VALUES ($key, $state);
            """,
            {
                "$key": (self._key(key), ydb.PrimitiveType.Utf8),
                "$state": (value, ydb.OptionalType(ydb.PrimitiveType.Utf8)),
            },
            retry_settings=ydb.RetrySettings(idempotent=True),
        )

    async def get_state(self, key: StorageKey) -> str | None:
        result_sets = await self._ydb.pool.execute_with_retries(
            """
            DECLARE $key AS Utf8;

            SELECT state FROM fsm_storage WHERE key = $key;
            """,
            {"$key": (self._key(key), ydb.PrimitiveType.Utf8)},
            retry_settings=ydb.RetrySettings(idempotent=True),
        )
        rows = result_sets[0].rows
        if not rows:
            return None
        return rows[0].state

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(data), ensure_ascii=False)
        await self._ydb.pool.execute_with_retries(
            """
            DECLARE $key AS Utf8;
            DECLARE $data AS Json;

            UPSERT INTO fsm_storage (key, data)
            VALUES ($key, $data);
            """,
            {
                "$key": (self._key(key), ydb.PrimitiveType.Utf8),
                "$data": (payload, ydb.PrimitiveType.Json),
            },
            retry_settings=ydb.RetrySettings(idempotent=True),
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        result_sets = await self._ydb.pool.execute_with_retries(
            """
            DECLARE $key AS Utf8;

            SELECT data FROM fsm_storage WHERE key = $key;
            """,
            {"$key": (self._key(key), ydb.PrimitiveType.Utf8)},
            retry_settings=ydb.RetrySettings(idempotent=True),
        )
        rows = result_sets[0].rows
        if not rows or rows[0].data is None:
            return {}
        raw = rows[0].data
        if isinstance(raw, dict):
            return raw
        return json.loads(raw)

    async def close(self) -> None:
        return None

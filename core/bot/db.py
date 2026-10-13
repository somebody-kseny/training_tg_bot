from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from time import perf_counter
from typing import Any

import ydb
import ydb.aio
import ydb.iam
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


async def _execute_query(
    pool: ydb.aio.QuerySessionPool,
    operation: str,
    query: str,
    parameters: dict[str, Any],
    retry_settings: ydb.RetrySettings,
) -> Any:
    started_at = perf_counter()
    logger.info("YDB запрос начат: %s", operation)
    try:
        result = await pool.execute_with_retries(
            query,
            parameters,
            retry_settings=retry_settings,
        )
    except Exception:
        logger.info("YDB запрос завершился ошибкой: %s", operation)
        raise
    logger.info(
        "YDB запрос завершён: %s, duration_ms=%.1f",
        operation,
        (perf_counter() - started_at) * 1_000,
    )
    return result


def _credentials() -> Any:
    if os.getenv("YDB_ANONYMOUS_CREDENTIALS") == "1":
        return ydb.AnonymousCredentials()
    token = os.getenv("YDB_ACCESS_TOKEN_CREDENTIALS")
    if token:
        return ydb.AccessTokenCredentials(token)
    sa_file = os.getenv("YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS")
    if sa_file:
        return ydb.iam.ServiceAccountCredentials.from_file(sa_file)
    return ydb.iam.MetadataUrlCredentials()


@dataclass(slots=True)
class User:
    telegram_id: int
    username: str | None
    name: str | None


@dataclass(slots=True)
class TrainingEntry:
    id: str
    name: str
    training_date: date
    source: str
    details: str | None = None
    distance: float | None = None
    created_at: Any = None


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
        await _execute_query(
            self._ydb.pool,
            "users.upsert",
            """
            DECLARE $telegramId AS Int64;
            DECLARE $username AS Optional<Utf8>;
            DECLARE $name AS Utf8;

            UPSERT INTO users (telegram_id, username, name, updated_at)
            VALUES ($telegramId, $username, $name, CurrentUtcTimestamp());
            """,
            params,
            retry,
        )
        await _execute_query(
            self._ydb.pool,
            "users.set_created_at",
            """
            DECLARE $telegramId AS Int64;

            UPDATE users
            SET created_at = CurrentUtcTimestamp()
            WHERE telegram_id = $telegramId AND created_at IS NULL;
            """,
            {"$telegramId": params["$telegramId"]},
            retry,
        )

    async def get(self, telegram_id: int) -> User | None:
        result_sets = await _execute_query(
            self._ydb.pool,
            "users.get",
            """
            DECLARE $telegramId AS Int64;

            SELECT telegram_id, username, name
            FROM users
            WHERE telegram_id = $telegramId;
            """,
            {"$telegramId": (telegram_id, ydb.PrimitiveType.Int64)},
            ydb.RetrySettings(idempotent=True),
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


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


class _TrainingRepo:
    def __init__(self, ydb_client: YdbClient, table: str) -> None:
        self._ydb = ydb_client
        self._table = table

    async def insert(
        self,
        record_id: str,
        telegram_id: int,
        name: str,
        training_date: date,
        details: str | None = None,
    ) -> None:
        await _execute_query(
            self._ydb.pool,
            f"{self._table}.insert",
            f"""
            DECLARE $id AS Utf8;
            DECLARE $telegramId AS Int64;
            DECLARE $name AS Utf8;
            DECLARE $trainingDate AS Date;
            DECLARE $details AS Optional<Utf8>;

            UPSERT INTO {self._table} (id, telegram_id, name, created_at, training_date, details)
            VALUES ($id, $telegramId, $name, CurrentUtcTimestamp(), $trainingDate, $details);
            """,
            {
                "$id": (record_id, ydb.PrimitiveType.Utf8),
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$name": (name, ydb.PrimitiveType.Utf8),
                "$trainingDate": (training_date, ydb.PrimitiveType.Date),
                "$details": (details, ydb.OptionalType(ydb.PrimitiveType.Utf8)),
            },
            ydb.RetrySettings(idempotent=True),
        )

    async def list_between(
        self,
        telegram_id: int,
        date_from: date,
        date_to: date,
    ) -> list[TrainingEntry]:
        result_sets = await _execute_query(
            self._ydb.pool,
            f"{self._table}.list_between",
            f"""
            DECLARE $telegramId AS Int64;
            DECLARE $dateFrom AS Date;
            DECLARE $dateTo AS Date;

            SELECT id, name, training_date, details, created_at
            FROM {self._table}
            WHERE telegram_id = $telegramId
              AND training_date >= $dateFrom
              AND training_date <= $dateTo;
            """,
            {
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$dateFrom": (date_from, ydb.PrimitiveType.Date),
                "$dateTo": (date_to, ydb.PrimitiveType.Date),
            },
            ydb.RetrySettings(idempotent=True),
        )
        entries: list[TrainingEntry] = []
        for row in result_sets[0].rows:
            entries.append(
                TrainingEntry(
                    id=str(row.id),
                    name=str(row.name),
                    training_date=_as_date(row.training_date),
                    source=self._table,
                    details=_optional_str(row.details),
                    created_at=row.created_at,
                )
            )
        return entries

    async def get(self, telegram_id: int, record_id: str) -> TrainingEntry | None:
        result_sets = await _execute_query(
            self._ydb.pool,
            f"{self._table}.get",
            f"""
            DECLARE $telegramId AS Int64;
            DECLARE $id AS Utf8;

            SELECT id, name, training_date, details, created_at
            FROM {self._table}
            WHERE telegram_id = $telegramId AND id = $id;
            """,
            {
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$id": (record_id, ydb.PrimitiveType.Utf8),
            },
            ydb.RetrySettings(idempotent=True),
        )
        rows = result_sets[0].rows
        if not rows:
            return None
        row = rows[0]
        return TrainingEntry(
            id=str(row.id),
            name=str(row.name),
            training_date=_as_date(row.training_date),
            source=self._table,
            details=_optional_str(row.details),
            created_at=row.created_at,
        )

    async def delete(self, telegram_id: int, record_id: str) -> None:
        await _execute_query(
            self._ydb.pool,
            f"{self._table}.delete",
            f"""
            DECLARE $telegramId AS Int64;
            DECLARE $id AS Utf8;

            DELETE FROM {self._table}
            WHERE telegram_id = $telegramId AND id = $id;
            """,
            {
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$id": (record_id, ydb.PrimitiveType.Utf8),
            },
            ydb.RetrySettings(idempotent=True),
        )


class ClimbingRepo(_TrainingRepo):
    def __init__(self, ydb_client: YdbClient) -> None:
        super().__init__(ydb_client, "climbing")


class CardioRepo:
    def __init__(self, ydb_client: YdbClient) -> None:
        self._ydb = ydb_client

    async def insert(
        self,
        record_id: str,
        telegram_id: int,
        name: str,
        distance: float,
        training_date: date,
        details: str | None = None,
    ) -> None:
        await _execute_query(
            self._ydb.pool,
            "cardio.insert",
            """
            DECLARE $id AS Utf8;
            DECLARE $telegramId AS Int64;
            DECLARE $name AS Utf8;
            DECLARE $distance AS Double;
            DECLARE $trainingDate AS Date;
            DECLARE $details AS Optional<Utf8>;

            UPSERT INTO cardio (id, telegram_id, name, distance, created_at, training_date, details)
            VALUES ($id, $telegramId, $name, $distance, CurrentUtcTimestamp(), $trainingDate, $details);
            """,
            {
                "$id": (record_id, ydb.PrimitiveType.Utf8),
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$name": (name, ydb.PrimitiveType.Utf8),
                "$distance": (distance, ydb.PrimitiveType.Double),
                "$trainingDate": (training_date, ydb.PrimitiveType.Date),
                "$details": (details, ydb.OptionalType(ydb.PrimitiveType.Utf8)),
            },
            ydb.RetrySettings(idempotent=True),
        )

    async def list_between(
        self,
        telegram_id: int,
        date_from: date,
        date_to: date,
    ) -> list[TrainingEntry]:
        result_sets = await _execute_query(
            self._ydb.pool,
            "cardio.list_between",
            """
            DECLARE $telegramId AS Int64;
            DECLARE $dateFrom AS Date;
            DECLARE $dateTo AS Date;

            SELECT id, name, distance, training_date, details, created_at
            FROM cardio
            WHERE telegram_id = $telegramId
              AND training_date >= $dateFrom
              AND training_date <= $dateTo;
            """,
            {
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$dateFrom": (date_from, ydb.PrimitiveType.Date),
                "$dateTo": (date_to, ydb.PrimitiveType.Date),
            },
            ydb.RetrySettings(idempotent=True),
        )
        entries: list[TrainingEntry] = []
        for row in result_sets[0].rows:
            entries.append(
                TrainingEntry(
                    id=str(row.id),
                    name=str(row.name),
                    training_date=_as_date(row.training_date),
                    source="cardio",
                    details=_optional_str(row.details),
                    distance=float(row.distance) if row.distance is not None else None,
                    created_at=row.created_at,
                )
            )
        return entries

    async def get(self, telegram_id: int, record_id: str) -> TrainingEntry | None:
        result_sets = await _execute_query(
            self._ydb.pool,
            "cardio.get",
            """
            DECLARE $telegramId AS Int64;
            DECLARE $id AS Utf8;

            SELECT id, name, distance, training_date, details, created_at
            FROM cardio
            WHERE telegram_id = $telegramId AND id = $id;
            """,
            {
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$id": (record_id, ydb.PrimitiveType.Utf8),
            },
            ydb.RetrySettings(idempotent=True),
        )
        rows = result_sets[0].rows
        if not rows:
            return None
        row = rows[0]
        return TrainingEntry(
            id=str(row.id),
            name=str(row.name),
            training_date=_as_date(row.training_date),
            source="cardio",
            details=_optional_str(row.details),
            distance=float(row.distance) if row.distance is not None else None,
            created_at=row.created_at,
        )

    async def delete(self, telegram_id: int, record_id: str) -> None:
        await _execute_query(
            self._ydb.pool,
            "cardio.delete",
            """
            DECLARE $telegramId AS Int64;
            DECLARE $id AS Utf8;

            DELETE FROM cardio
            WHERE telegram_id = $telegramId AND id = $id;
            """,
            {
                "$telegramId": (telegram_id, ydb.PrimitiveType.Int64),
                "$id": (record_id, ydb.PrimitiveType.Utf8),
            },
            ydb.RetrySettings(idempotent=True),
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
        await _execute_query(
            self._ydb.pool,
            "fsm.set_state",
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
            ydb.RetrySettings(idempotent=True),
        )

    async def get_state(self, key: StorageKey) -> str | None:
        result_sets = await _execute_query(
            self._ydb.pool,
            "fsm.get_state",
            """
            DECLARE $key AS Utf8;

            SELECT state FROM fsm_storage WHERE key = $key;
            """,
            {"$key": (self._key(key), ydb.PrimitiveType.Utf8)},
            ydb.RetrySettings(idempotent=True),
        )
        rows = result_sets[0].rows
        if not rows:
            return None
        return rows[0].state

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(data), ensure_ascii=False)
        await _execute_query(
            self._ydb.pool,
            "fsm.set_data",
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
            ydb.RetrySettings(idempotent=True),
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        result_sets = await _execute_query(
            self._ydb.pool,
            "fsm.get_data",
            """
            DECLARE $key AS Utf8;

            SELECT data FROM fsm_storage WHERE key = $key;
            """,
            {"$key": (self._key(key), ydb.PrimitiveType.Utf8)},
            ydb.RetrySettings(idempotent=True),
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

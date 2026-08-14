from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    ydb_endpoint: str
    ydb_database: str
    webhook_secret: str | None

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.getenv("WEBHOOK_SECRET", "").strip()
        return cls(
            bot_token=_require("BOT_TOKEN"),
            ydb_endpoint=_require("YDB_ENDPOINT"),
            ydb_database=_require("YDB_DATABASE"),
            webhook_secret=secret or None,
        )

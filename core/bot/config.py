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
    telegram_api_base: str
    ydb_endpoint: str
    ydb_database: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            bot_token=_require("BOT_TOKEN"),
            telegram_api_base=_require("TELEGRAM_API_BASE"),
            ydb_endpoint=_require("YDB_ENDPOINT"),
            ydb_database=_require("YDB_DATABASE"),
        )

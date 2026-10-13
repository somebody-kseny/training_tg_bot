from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 8000
DEFAULT_WEBHOOK_PATH = "/foo"


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


def _optional(name: str) -> str:
    return os.getenv(name, "").strip()


def _webhook_path(webhook_url: str) -> str:
    configured = _optional("WEBHOOK_PATH")
    if configured:
        return configured if configured.startswith("/") else f"/{configured}"
    if webhook_url:
        path = urlsplit(webhook_url).path.strip()
        if path:
            return path
    return DEFAULT_WEBHOOK_PATH


def _listen_port() -> int:
    raw = _optional("LISTEN_PORT")
    if not raw:
        return DEFAULT_LISTEN_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("LISTEN_PORT должен быть числом") from exc
    if not (1 <= port <= 65535):
        raise RuntimeError("LISTEN_PORT должен быть в диапазоне 1–65535")
    return port


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    telegram_api_base: str
    ydb_endpoint: str
    ydb_database: str
    webhook_secret: str
    webhook_url: str
    webhook_path: str
    listen_port: int

    @classmethod
    def from_env(cls) -> Settings:
        webhook_url = _optional("WEBHOOK_URL")
        return cls(
            bot_token=_require("BOT_TOKEN"),
            telegram_api_base=_require("TELEGRAM_API_BASE"),
            ydb_endpoint=_require("YDB_ENDPOINT"),
            ydb_database=_require("YDB_DATABASE"),
            webhook_secret=_optional("WEBHOOK_SECRET"),
            webhook_url=webhook_url,
            webhook_path=_webhook_path(webhook_url),
            listen_port=_listen_port(),
        )

    def require_webhook_secret(self) -> None:
        if not self.webhook_secret:
            raise RuntimeError("Не задана переменная окружения WEBHOOK_SECRET")

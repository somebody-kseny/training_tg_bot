"""Лёгкий proxy: принимает webhook Telegram и асинхронно дергает core."""

from __future__ import annotations

import base64
import logging
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

_OK = {"statusCode": 200, "body": "ok"}


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


def _headers(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("headers") or {}
    return {str(key).lower(): str(value) for key, value in raw.items()}


def _body_bytes(event: dict[str, Any]) -> bytes:
    body = event.get("body")
    if body in (None, ""):
        return b""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return str(body).encode("utf-8")


def _async_invoke_url(base_url: str) -> str:
    parts = urlsplit(base_url.strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["integration"] = "async"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _is_secret_valid(event: dict[str, Any]) -> bool:
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not secret:
        return True
    token = _headers(event).get("x-telegram-bot-api-secret-token")
    return token == secret


def _invoke_core(body: bytes) -> int:
    url = _async_invoke_url(_require("CORE_FUNCTION_URL"))
    api_key = _require("CORE_INVOKE_API_KEY")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return int(response.status)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = str(event.get("httpMethod") or "POST").upper()
    logger.info("Proxy: method=%s", method)

    if method in {"GET", "HEAD"}:
        return _OK

    if not _is_secret_valid(event):
        logger.info("Отклонён запрос с неверным webhook secret")
        return {"statusCode": 403, "body": "forbidden"}

    body = _body_bytes(event)
    if not body:
        logger.info("Пустое тело — отвечаем 200 без вызова core")
        return _OK

    try:
        status = _invoke_core(body)
    except urllib.error.HTTPError as exc:
        logger.exception("Ошибка HTTP при вызове core: status=%s", exc.code)
        return {"statusCode": 500, "body": "invoke failed"}
    except Exception:
        logger.exception("Не удалось вызвать core")
        return {"statusCode": 500, "body": "invoke failed"}

    if status not in {200, 202}:
        logger.error("Core вернул неожиданный статус: %s", status)
        return {"statusCode": 500, "body": "invoke failed"}

    logger.info("Core принял update асинхронно: status=%s", status)
    return _OK

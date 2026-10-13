# Trens-bot

Telegram-бот на aiogram 3 + YDB в Yandex Cloud Functions.

Чтобы Telegram не ждал долгую обработку, webhook разбит на две функции:

| Функция | Роль | Документация |
| --- | --- | --- |
| **proxy** | Публичный webhook: проверить secret → async-вызов core → сразу `200` | [proxy/README.md](proxy/README.md) |
| **core** | Приватная обработка update и ответы в чат | [core/README.md](core/README.md) |

```text
Telegram → proxy (200) → async invoke → core → Bot API
```

На `/start` бот спрашивает имя и сохраняет в таблицу `users` телеграм-ник и имя.

## Переменные окружения

Общий шаблон: [`.env.example`](.env.example).

**proxy:** `WEBHOOK_SECRET`, `CORE_FUNCTION_URL`, `CORE_INVOKE_API_KEY`  
**core:** `BOT_TOKEN`, `YDB_ENDPOINT`, `YDB_DATABASE` (+ credentials для локального YDB)

## YDB

Таблицы из [`schema.sql`](schema.sql) создать вручную в консоли YDB до запуска core.

Таблица `users`:

- `telegram_id` — первичный ключ
- `username` — ник в Telegram (без `@`, может быть пустым)
- `name` — имя, которое прислал пользователь

## Сборка zip

```bash
./scripts/package.sh
```

Получатся `build/core.zip` и `build/proxy.zip`. Скрипт идёт по списку `FUNCTIONS=(core proxy)` без копипасты.

## Деплой (порядок)

1. Подготовить YDB и SA для core (`ydb.editor`).
2. Задеплоить **core**: runtime `python312`, entrypoint `index.handler`, **приватный** вызов, SA с доступом к YDB, env core, включить async invocation на версии.
3. Создать API-ключ для SA с ролью `functions.functionInvoker` на core (scope `yc.serverless.functions.invoke`).
4. Задеплоить **proxy**: публичный вызов, env proxy (`CORE_FUNCTION_URL` = URL core без query, ключ, secret).
5. `setWebhook` на URL **proxy**:

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "content-type: application/json" \
  -d '{"url":"https://functions.yandexcloud.net/<proxy-id>","secret_token":"<WEBHOOK_SECRET>"}'
```

Детали и нюансы auth/async — в README каждой функции.

## Локальный запуск (long polling)

Только логика бота (каталог `core`):

```bash
cd core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# заполните .env
python3 -m bot
```

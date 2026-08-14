# Core Telegram-бот на aiogram 3 + YDB для Yandex Cloud Functions.

На `/start` бот спрашивает имя и сохраняет в таблицу `users` телеграм-ник и имя.

## Переменные окружения

| Имя | Описание |
| --- | --- |
| `BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather) |
| `YDB_ENDPOINT` | Endpoint YDB, например `grpcs://ydb.serverless.yandexcloud.net:2135` |
| `YDB_DATABASE` | Путь БД, например `/ru-central1/.../...` |
| `WEBHOOK_SECRET` | Необязательный секрет webhook Telegram |

В Cloud Functions авторизация в YDB идёт через metadata-сервис сервисного аккаунта. Локально задайте `YDB_ANONYMOUS_CREDENTIALS=1`, `YDB_ACCESS_TOKEN_CREDENTIALS` или `YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS`.

## YDB

Нужны таблицы из `schema.sql`. Выполните SQL вручную в консоли YDB до запуска функции.

Таблица `users`:

- `telegram_id` — первичный ключ
- `username` — ник в Telegram (без `@`, может быть пустым)
- `name` — имя, которое прислал пользователь

## Деплой в Cloud Functions

1. Сервисный аккаунт с ролью `ydb.editor` на базу. Таблицы создать заранее по `schema.sql`.
2. Функция: runtime `python312`, точка входа `index.handler`, публичный вызов, этот сервисный аккаунт, переменные окружения выше.
3. Загрузить zip с кодом (`index.py`, `requirements.txt`, каталог `bot/`).
4. Повесить webhook:

```bash
curl -X POST "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
  -H "content-type: application/json" \
  -d "{\"url\": \"https://functions.yandexcloud.net/<function_id>\", \"secret_token\": \"$WEBHOOK_SECRET\"}"
```

## Локальный запуск (long polling)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполните .env
python -m bot
```

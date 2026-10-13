# Core — обработка Telegram update

Приватная Cloud Function: принимает JSON update (тот же, что прислал Telegram), гоняет его через aiogram и отвечает пользователю. Вызывается только из **proxy** асинхронно.

## Зачем

Вся тяжёлая работа (aiogram, YDB, бизнес-логика) здесь. Proxy уже ответил Telegram `200`, поэтому длительность core не влияет на таймаут webhook.

## Контракт входа

Единственный формат event — **сырое тело** async-invoke от proxy: JSON Telegram `Update` (есть поле `update_id`).

При `?integration=async` Yandex Cloud Functions передаёт в handler тело HTTPS-запроса **без** HTTP-обёртки (`httpMethod` / `headers` / `body` нет). Поэтому:

- `WEBHOOK_SECRET` здесь **не** проверяется (секрет смотрит только proxy);
- доступ к функции закрыт платформой: приватный вызов + `Authorization: Api-Key …` у proxy.

Handler принимает:

- `str` / `bytes` → `json.loads` → dict с `update_id`;
- уже распарсенный `dict` с `update_id` (если рантайм так отдаст).

Другие формы (HTTP API Gateway event и т.п.) **не** поддерживаются.

## Переменные окружения

| Имя | Описание |
| --- | --- |
| `BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_API_BASE` | Base URL Bot API (прокси) |
| `YDB_ENDPOINT` | Endpoint YDB, например `grpcs://ydb.serverless.yandexcloud.net:2135` |
| `YDB_DATABASE` | Путь БД, например `/ru-central1/.../...` |

В Cloud Functions доступ к YDB — через metadata сервисного аккаунта функции. Локально: `YDB_ANONYMOUS_CREDENTIALS=1`, `YDB_ACCESS_TOKEN_CREDENTIALS` или `YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS`.

## Права и доступ

- Функция **приватная** (вызов только с авторизацией).
- На версии функции включить **асинхронный вызов** (async invocation) и задать SA для async, число ретраев при необходимости.
- Сервисный аккаунт функции: роль `ydb.editor` на базу; исходящая сеть до `TELEGRAM_API_BASE` (прокси Bot API).
- Вызывающий (API-ключ proxy) — роль `functions.functionInvoker` на эту функцию.

## Точка входа и зависимости

- Runtime: `python312`
- Entry point: `index.handler`
- Зависимости: [`requirements.txt`](requirements.txt) (`aiogram`, `ydb`, `python-dotenv`)

## Сборка

```bash
./scripts/package.sh
```

Артефакт: `build/core.zip` (`index.py`, `requirements.txt`, пакет `bot/`).

## Поведение

1. Распарсить update.
2. Инициализировать bot + dispatcher + YDB (кэш на тёплых инстансах).
3. `dispatcher.feed_update(...)` — хендлеры (`/start`, climb и т.д.).
4. Вернуть `{statusCode: 200, body: "ok"}` (для async статус клиенту уже отдала платформа как `202`).

## Локальный запуск (long polling)

Для отладки логики бота без Cloud Functions:

```bash
cd core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# заполните BOT_TOKEN и YDB_*
python3 -m bot
```

Webhook-путь (`index.handler`) локально не эмулирует async-контракт proxy — для этого нужен деплой пары функций.

Подробности proxy — в [proxy/README.md](../proxy/README.md). Общая схема — в [корневом README](../README.md).

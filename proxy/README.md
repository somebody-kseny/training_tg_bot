# Proxy — webhook для Telegram

Публичная Cloud Function: принимает update от Telegram, быстро отвечает `200`, а обработку отдаёт приватной функции **core** через асинхронный вызов.

## Зачем

Telegram ждёт быстрый HTTP-ответ на webhook. Холодный старт, YDB и aiogram в одной функции часто не укладываются в ожидания Telegram → повторные доставки одного и того же update. Proxy только проверяет секрет и ставит задачу в core.

## Поток

1. Telegram шлёт `POST` с JSON update и заголовком `X-Telegram-Bot-Api-Secret-Token`.
2. Proxy проверяет `WEBHOOK_SECRET`.
3. Proxy делает `POST` на URL core с `?integration=async` и заголовком `Authorization: Api-Key …`.
4. Платформа отвечает `202` — вызов принят в очередь, без ожидания конца обработки.
5. Proxy сразу отвечает Telegram `200 ok`.
6. Core уже отдельно обрабатывает update и пишет в чат через Bot API.

При ошибке вызова core proxy логирует проблему и отвечает Telegram `500` (без сообщения пользователю), чтобы Telegram мог повторить доставку.

## Переменные окружения

| Имя | Описание |
| --- | --- |
| `WEBHOOK_SECRET` | Тот же `secret_token`, что в `setWebhook`. Если пусто — проверка отключена (не для продакшена). |
| `CORE_FUNCTION_URL` | HTTPS URL core, например `https://functions.yandexcloud.net/<core-id>` **без** query. Код сам добавит `integration=async`. |
| `CORE_INVOKE_API_KEY` | [API-ключ](https://yandex.cloud/ru/docs/iam/operations/authentication/manage-api-keys) сервисного аккаунта с правом вызывать core. |

## Права и доступ

- Функция **публичная** (вызов без авторизации) — иначе Telegram не достучится.
- Сервисный аккаунт, для которого создан API-ключ, должен иметь роль `functions.functionInvoker` на функцию **core**.
- При создании API-ключа желательно указать scope `yc.serverless.functions.invoke`.
- Сам proxy может работать без сервисного аккаунта (YDB не использует); ключ только в env.

## Точка входа и зависимости

- Runtime: `python312`
- Entry point: `index.handler`
- Зависимости: только стандартная библиотека (`requirements.txt` пустой по смыслу, файл нужен платформе)

## Сборка

Из корня репозитория:

```bash
./scripts/package.sh
```

Артефакт: `build/proxy.zip` (внутри `index.py` и `requirements.txt`).

## Деплой (кратко)

1. Создать функцию, загрузить `build/proxy.zip`, выставить env выше, публичный вызов.
2. Убедиться, что core уже задеплоена, приватная, с включённым async invocation.
3. Повесить webhook Telegram на URL **этой** функции (не core):

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "content-type: application/json" \
  -d '{"url":"https://functions.yandexcloud.net/<proxy-id>","secret_token":"<WEBHOOK_SECRET>"}'
```

Подробности по core — в [core/README.md](../core/README.md). Общая схема репозитория — в [корневом README](../README.md).

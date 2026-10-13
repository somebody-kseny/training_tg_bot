# Core — Telegram-бот на отдельном сервере

Долгоживущий процесс на VPS: принимает webhook от Telegram, обрабатывает update через aiogram и отвечает в чат. Данные — в **Yandex YDB**. Яндекс Функции не используются.

С интернета бот доступен только через **nginx на 443** с TLS. Само приложение слушает `127.0.0.1:8000` и из сети не видно.

```text
Telegram → nginx :443 (сразу 200) ──mirror──→ 127.0.0.1:8000 → aiogram → YDB / Bot API
```

## Поток

1. Telegram шлёт `POST` на `https://<server_domen>/foo` с JSON update и заголовком `X-Telegram-Bot-Api-Secret-Token`.
2. nginx проверяет secret, через `mirror` отдаёт тело на `127.0.0.1:8000/foo`, а Telegramу отвечает `200` через локальный ack на `127.0.0.1:18080` (**не** `return 200` и **не** `empty_gif`: иначе mirror не сработает или POST получит 405).
3. При старте процесс вызывает `setWebhook` (`WEBHOOK_URL` + `WEBHOOK_SECRET`); при остановке — `deleteWebhook`.
4. Процесс ещё раз проверяет secret, обрабатывает update и пишет в чат через Bot API (`TELEGRAM_API_BASE`).
5. Хендлеры (`/start`, climb и т.д.) ходят в YDB и в Bot API.

Проверка mirror: после `reload` в `/var/log/nginx/trens-mirror.log` и в логах бота должны появляться записи на каждый POST.

## Переменные окружения

Шаблон: [`.env.example`](../.env.example). Рядом с процессом — файл `core/.env`.

| Имя | Описание |
| --- | --- |
| `BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_API_BASE` | Base URL Bot API (прямой `https://api.telegram.org` или ваш прокси) |
| `WEBHOOK_SECRET` | Тот же `secret_token`, что в `setWebhook`. Обязателен в режиме webhook |
| `WEBHOOK_URL` | Публичный HTTPS URL, например `https://<server_domen>/foo`. Если задан — при старте вызывается `setWebhook` |
| `WEBHOOK_PATH` | Путь приложения, по умолчанию `/foo` (должен совпадать с `location` в nginx) |
| `LISTEN_PORT` | Локальный порт, по умолчанию `8000`. Хост всегда `127.0.0.1`, снаружи не слушает |
| `YDB_ENDPOINT` | Endpoint YDB, например `grpcs://ydb.serverless.yandexcloud.net:2135` |
| `YDB_DATABASE` | Путь БД, например `/ru-central1/.../...` |

На сервере доступ к YDB — через ключ сервисного аккаунта: `YDB_SERVICE_ACCOUNT_KEY_FILE_CREDENTIALS=/path/to/sa-key.json`. У SA роль `ydb.editor` на базу.

Локально можно `YDB_ANONYMOUS_CREDENTIALS=1`, `YDB_ACCESS_TOKEN_CREDENTIALS` или тот же файл ключа.

## Сеть и TLS

Порт приложения **не публиковать** (ни `LISTEN_PORT`, ни 8000 в security group / ufw / iptables). Открыть снаружи только 443 (и 80 — для Let's Encrypt и редиректа на HTTPS).

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 8000/tcp
sudo ufw enable
```

Заготовка nginx: [`nginx_configs/core_deploy`](../nginx_configs/core_deploy). Подставьте домен (`<server_domen>`) и секрет webhook (`<webhook_secret>` — тот же, что `WEBHOOK_SECRET`), положите в `sites-available`, включите сайт.

```bash
sudo ln -s /etc/nginx/sites-available/core_deploy /etc/nginx/sites-enabled/core_deploy
sudo nginx -t && sudo systemctl reload nginx
```

Сертификат (после того как A-запись домена смотрит на сервер):

```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d <server_domen>
sudo nginx -t && sudo systemctl reload nginx
```

Проверка, что бот не торчит в интернет:

```bash
ss -tlnp | grep 8000
# ожидается: 127.0.0.1:8000
```

## Запуск на сервере

```bash
cd /opt/trens-bot/core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# заполните BOT_TOKEN, TELEGRAM_API_BASE, WEBHOOK_SECRET, WEBHOOK_URL, YDB_*
```

Юнит systemd: [`trens-bot.service`](trens-bot.service). Поправьте пути и пользователя, затем:

```bash
sudo cp trens-bot.service /etc/systemd/system/trens-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now trens-bot
sudo systemctl status trens-bot
```

Точка входа: `python -m bot` (или `python index.py`). Процесс слушает только localhost.

`WEBHOOK_URL` и `WEBHOOK_SECRET` обязательны в режиме webhook: при старте — `setWebhook`, при Ctrl+C / `systemctl stop` — `deleteWebhook`. URL — публичный HTTPS через nginx (`https://<server_domen>/foo`), не `http://IP:8000`.

## Зависимости

- Python 3.12+
- [`requirements.txt`](requirements.txt): `aiogram`, `ydb`, `python-dotenv` (`aiohttp` приходит с aiogram)

## Локальный запуск (long polling)

Без nginx, для отладки логики:

```bash
cd core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# заполните BOT_TOKEN и YDB_*
python3 -m bot --poll
```

# Телеграм-бот

Маленький telegram-бот для логирования спортивных тренировок (скалолазание, бег, велосипед): запись, просмотр и удаление через диалог в чате.

## Техническое описание

Webhook-сервис на Python: nginx → локальный aiohttp → aiogram 3 → **Yandex YDB** (данные тренировок и FSM-хранилище). Деплой — systemd на VPS, снаружи - только через nginx (настроен фаервол UFW).

**Стек:**

- Python 3
- aiogram 3
- aiohttp
- python-dotenv
- Yandex YDB (`ydb` SDK)
- nginx, systemd

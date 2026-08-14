-- Выполнить в консоли YDB до запуска функции.

CREATE TABLE IF NOT EXISTS users (
    telegram_id Int64 NOT NULL,
    username Utf8,
    name Utf8,
    created_at Timestamp,
    updated_at Timestamp,
    PRIMARY KEY (telegram_id)
);

CREATE TABLE IF NOT EXISTS fsm_storage (
    key Utf8 NOT NULL,
    state Utf8,
    data Json,
    PRIMARY KEY (key)
);

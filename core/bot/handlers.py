from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import UsersRepo
from bot.ready import send_ready_prompt
from bot.send import answer
from bot.states import Registration

router = Router(name="start")
logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 64


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info("Обработчик /start: сохраняю FSM-состояние")
    await state.set_state(Registration.name)
    logger.info("Обработчик /start: отправляю ответ в Telegram")
    await answer(message, "Привет! Как тебя зовут?")
    logger.info("Обработчик /start: ответ Telegram отправлен")


@router.message(Registration.name, F.text)
async def save_name(message: Message, state: FSMContext, users: UsersRepo) -> None:
    name = (message.text or "").strip()
    if not name or name.startswith("/") or len(name) > MAX_NAME_LENGTH:
        logger.info("Обработчик имени: отправляю сообщение о некорректном имени")
        await answer(
            message,
            "Пришли обычное имя текстом, без команды. До 64 символов.",
        )
        logger.info("Обработчик имени: сообщение Telegram отправлено")
        return

    from_user = message.from_user
    if from_user is None:
        logger.info("Обработчик имени: сообщение без from_user")
        return

    logger.info("Обработчик имени: сохраняю пользователя в YDB")
    await users.upsert(
        telegram_id=from_user.id,
        username=from_user.username,
        name=name,
    )
    logger.info("Обработчик имени: очищаю FSM-состояние")
    await state.clear()
    logger.info("Обработчик имени: отправляю подтверждение в Telegram")
    await answer(
        message,
        f"Запомнил: {name}. Имя будет использоваться при формировании рейтинга. "
        "Поменять его можно повторно вызвав команду /start",
    )
    await send_ready_prompt(message, state)
    logger.info("Регистрация пользователя завершена: telegram_id=%s", from_user.id)


@router.message(Registration.name)
async def name_expected(message: Message) -> None:
    logger.info("Обработчик имени: отправляю подсказку")
    await answer(message, "Пришли имя текстом.")
    logger.info("Обработчик имени: подсказка Telegram отправлена")

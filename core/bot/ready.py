from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.send import answer

logger = logging.getLogger(__name__)

READY_TEXT = (
    "Бот готов к работе. Отправьте команду. "
    "Команды можно увидеть в меню, которое открывается нажатием на кнопку или вводом слэша."
)
READY_MESSAGE_ID_KEY = "ready_message_id"


async def delete_ready_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    message_id = data.get(READY_MESSAGE_ID_KEY)
    if not isinstance(message_id, int) or message.bot is None:
        return

    try:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=message_id)
    except TelegramBadRequest:
        logger.info("Не удалось удалить сообщение готовности: message_id=%s", message_id)

    await state.update_data(**{READY_MESSAGE_ID_KEY: None})


async def send_ready_prompt(message: Message, state: FSMContext) -> None:
    await delete_ready_prompt(message, state)
    sent = await answer(message, READY_TEXT)
    await state.update_data(**{READY_MESSAGE_ID_KEY: sent.message_id})

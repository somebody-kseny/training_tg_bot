from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import UsersRepo
from bot.states import Registration

router = Router(name="start")

MAX_NAME_LENGTH = 64


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Registration.name)
    await message.answer("Привет! Как тебя зовут?")


@router.message(Registration.name, F.text)
async def save_name(message: Message, state: FSMContext, users: UsersRepo) -> None:
    name = (message.text or "").strip()
    if not name or name.startswith("/") or len(name) > MAX_NAME_LENGTH:
        await message.answer("Пришли обычное имя текстом, без команды. До 64 символов.")
        return

    from_user = message.from_user
    if from_user is None:
        return

    await users.upsert(
        telegram_id=from_user.id,
        username=from_user.username,
        name=name,
    )
    await state.clear()
    await message.answer(f"Запомнил, {name}!")


@router.message(Registration.name)
async def name_expected(message: Message) -> None:
    await message.answer("Пришли имя текстом.")

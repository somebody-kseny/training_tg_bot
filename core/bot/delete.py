from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import CardioRepo, ClimbingRepo, TrainingEntry
from bot.ready import send_ready_prompt
from bot.send import answer
from bot.states import Delete
from bot.training import cancel_training, parse_date

router = Router(name="delete")
logger = logging.getLogger(__name__)

PREFIX = "delete"
DATE_PROMPT = "Введите дату ошибочной тренировки в формате ДД.ММ.ГГГГ"
PROMPT_MESSAGE_ID_KEY = "prompt_message_id"
BUTTON_TEXT_LIMIT = 64
SOURCE_CODE = {
    "climbing": "k",
    "cardio": "c",
}
CODE_SOURCE = {code: source for source, code in SOURCE_CODE.items()}


def _format_distance(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g} км"


def entry_label(entry: TrainingEntry) -> str:
    if entry.distance is not None:
        line = f"{entry.name} {_format_distance(entry.distance)}"
    else:
        line = entry.name
    if entry.details:
        line = f"{line}, {entry.details}"
    return line


def _button_text(label: str) -> str:
    text = f"❌ {label}"
    if len(text) <= BUTTON_TEXT_LIMIT:
        return text
    return text[: BUTTON_TEXT_LIMIT - 1] + "…"


def _sort_key(entry: TrainingEntry) -> tuple:
    created = entry.created_at
    return (created is None, str(created or ""), entry.id)


def _entries_keyboard(entries: list[TrainingEntry]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for entry in sorted(entries, key=_sort_key):
        code = SOURCE_CODE.get(entry.source)
        if code is None:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_text(entry_label(entry)),
                    callback_data=f"{PREFIX}:{code}:{entry.id}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="отменить", callback_data=f"{PREFIX}:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _safe_delete(message: Message, message_id: int | None) -> None:
    if not isinstance(message_id, int) or message.bot is None:
        return
    try:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=message_id)
    except TelegramBadRequest:
        pass


async def _clear_prompt_exchange(message: Message, state: FSMContext) -> None:
    """Удаляет промпт бота и ответ пользователя (как при шагах даты/подробностей)."""
    data = await state.get_data()
    await _safe_delete(message, data.get(PROMPT_MESSAGE_ID_KEY))
    await _safe_delete(message, message.message_id)
    await state.update_data(**{PROMPT_MESSAGE_ID_KEY: None})


async def _ask_date(message: Message, state: FSMContext) -> None:
    sent = await answer(message, DATE_PROMPT)
    await state.update_data(**{PROMPT_MESSAGE_ID_KEY: sent.message_id})


async def _load_entries(
    telegram_id: int,
    day: date,
    climbing: ClimbingRepo,
    cardio: CardioRepo,
) -> list[TrainingEntry]:
    climbing_entries = await climbing.list_between(telegram_id, day, day)
    cardio_entries = await cardio.list_between(telegram_id, day, day)
    return [*climbing_entries, *cardio_entries]


async def _get_entry(
    telegram_id: int,
    record_id: str,
    source: str,
    climbing: ClimbingRepo,
    cardio: CardioRepo,
) -> TrainingEntry | None:
    if source == "climbing":
        return await climbing.get(telegram_id, record_id)
    return await cardio.get(telegram_id, record_id)


@router.message(Command("delete"))
async def cmd_delete(message: Message, state: FSMContext) -> None:
    logger.info("Обработчик /delete: запрос даты")
    await state.clear()
    await state.set_state(Delete.waiting_date)
    await _ask_date(message, state)


@router.message(Delete.waiting_date, F.text, ~F.text.startswith("/"))
async def delete_date_entered(
    message: Message,
    state: FSMContext,
    climbing: ClimbingRepo,
    cardio: CardioRepo,
) -> None:
    parsed = parse_date(message.text or "")
    if parsed is None:
        logger.info("Обработчик /delete: дата не подходит под формат")
        await _clear_prompt_exchange(message, state)
        await _ask_date(message, state)
        return

    from_user = message.from_user
    if from_user is None:
        return

    entries = await _load_entries(from_user.id, parsed, climbing, cardio)
    await _clear_prompt_exchange(message, state)

    if not entries:
        logger.info("Обработчик /delete: нет тренировок за %s", parsed.isoformat())
        await answer(message, "Нет тренировок за эту дату")
        await _ask_date(message, state)
        return

    await state.set_state(Delete.choosing)
    await answer(
        message,
        "Выберите тренировку для удаления:",
        reply_markup=_entries_keyboard(entries),
    )
    logger.info(
        "Обработчик /delete: показано %s тренировок за %s",
        len(entries),
        parsed.isoformat(),
    )


@router.message(Delete.waiting_date, ~F.text.startswith("/"))
async def delete_date_expected(message: Message, state: FSMContext) -> None:
    await _clear_prompt_exchange(message, state)
    await _ask_date(message, state)


@router.callback_query(F.data == f"{PREFIX}:cancel")
async def delete_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await cancel_training(callback, state)
    logger.info("Обработчик /delete: отмена")


@router.callback_query(F.data.startswith(f"{PREFIX}:"))
async def delete_entry(
    callback: CallbackQuery,
    state: FSMContext,
    climbing: ClimbingRepo,
    cardio: CardioRepo,
) -> None:
    parts = (callback.data or "").split(":", 2)
    from_user = callback.from_user
    if from_user is None or len(parts) != 3:
        await callback.answer()
        return

    _, code, record_id = parts
    source = CODE_SOURCE.get(code)
    if source is None or not record_id:
        await callback.answer()
        return

    entry = await _get_entry(from_user.id, record_id, source, climbing, cardio)
    if entry is None:
        await callback.answer("Тренировка уже удалена", show_alert=True)
        return

    label = entry_label(entry)
    if source == "climbing":
        await climbing.delete(from_user.id, record_id)
    else:
        await cardio.delete(from_user.id, record_id)

    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(f"× {label} удалена")
        except TelegramBadRequest:
            await answer(callback.message, f"× {label} удалена")
        await send_ready_prompt(callback.message, state)
    await callback.answer()
    logger.info(
        "Тренировка удалена: telegram_id=%s, source=%s, id=%s",
        from_user.id,
        source,
        record_id,
    )

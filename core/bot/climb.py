from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import ClimbingRepo
from bot.ready import send_ready_prompt
from bot.send import answer
from bot.states import Climb
from bot.training import (
    DATE_PROMPT,
    DETAILS_PROMPT,
    cancel_training,
    confirm_keyboard,
    confirm_text,
    draft_from_state,
    parse_date,
    today,
)

router = Router(name="climb")
logger = logging.getLogger(__name__)

PREFIX = "climb"
KIND_BY_CODE = {
    "boulder": "Болдер",
    "lead": "Трудность",
}


def _kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="болдер", callback_data=f"{PREFIX}:kind:boulder"),
                InlineKeyboardButton(text="трудность", callback_data=f"{PREFIX}:kind:lead"),
            ]
        ]
    )


@router.message(Command("climb"))
async def cmd_climb(message: Message, state: FSMContext) -> None:
    logger.info("Обработчик /climb: показываю выбор типа")
    await state.clear()
    await answer(
        message,
        "Выберите тип тренировки:",
        reply_markup=_kind_keyboard(),
    )


@router.callback_query(F.data.startswith(f"{PREFIX}:kind:"))
async def climb_kind(callback: CallbackQuery, state: FSMContext) -> None:
    code = (callback.data or "").rsplit(":", 1)[-1]
    kind = KIND_BY_CODE.get(code)
    if kind is None:
        await callback.answer()
        return

    training_date = today()
    await state.set_state(Climb.confirm)
    await state.update_data(kind=kind, training_date=training_date.isoformat(), details=None)
    text = confirm_text(kind, training_date)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=confirm_keyboard(PREFIX))
    await callback.answer()
    logger.info("Обработчик /climb: черновик %s", text)


@router.callback_query(F.data == f"{PREFIX}:date")
async def climb_ask_date(callback: CallbackQuery, state: FSMContext) -> None:
    if await draft_from_state(state) is None:
        await callback.answer("Начните с /climb", show_alert=True)
        return

    await state.set_state(Climb.waiting_date)
    if isinstance(callback.message, Message):
        await answer(callback.message, DATE_PROMPT)
    await callback.answer()
    logger.info("Обработчик /climb: запрос даты")


@router.message(Climb.waiting_date, F.text, ~F.text.startswith("/"))
async def climb_date_entered(message: Message, state: FSMContext) -> None:
    parsed = parse_date(message.text or "")
    if parsed is None:
        logger.info("Обработчик /climb: дата не подходит под формат")
        await answer(message, DATE_PROMPT)
        return

    draft = await draft_from_state(state)
    if draft is None:
        await state.clear()
        await answer(message, "Начните с /climb")
        return

    await state.set_state(Climb.confirm)
    await state.update_data(training_date=parsed.isoformat())
    text = confirm_text(draft.kind, parsed, details=draft.details)
    await answer(message, text, reply_markup=confirm_keyboard(PREFIX))
    logger.info("Обработчик /climb: черновик с датой %s", text)


@router.message(Climb.waiting_date, ~F.text.startswith("/"))
async def climb_date_expected(message: Message) -> None:
    await answer(message, DATE_PROMPT)


@router.callback_query(F.data == f"{PREFIX}:details")
async def climb_ask_details(callback: CallbackQuery, state: FSMContext) -> None:
    if await draft_from_state(state) is None:
        await callback.answer("Начните с /climb", show_alert=True)
        return

    await state.set_state(Climb.waiting_details)
    if isinstance(callback.message, Message):
        await answer(callback.message, DETAILS_PROMPT)
    await callback.answer()
    logger.info("Обработчик /climb: запрос подробностей")


@router.message(Climb.waiting_details, F.text, ~F.text.startswith("/"))
async def climb_details_entered(message: Message, state: FSMContext) -> None:
    details = (message.text or "").strip()
    if not details:
        await answer(message, DETAILS_PROMPT)
        return

    draft = await draft_from_state(state)
    if draft is None:
        await state.clear()
        await answer(message, "Начните с /climb")
        return

    await state.set_state(Climb.confirm)
    await state.update_data(details=details)
    text = confirm_text(draft.kind, draft.training_date, details=details)
    await answer(message, text, reply_markup=confirm_keyboard(PREFIX))
    logger.info("Обработчик /climb: черновик с подробностями")


@router.message(Climb.waiting_details, ~F.text.startswith("/"))
async def climb_details_expected(message: Message) -> None:
    await answer(message, DETAILS_PROMPT)


@router.callback_query(F.data == f"{PREFIX}:cancel")
async def climb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await cancel_training(callback, state)
    logger.info("Обработчик /climb: отмена, возврат в дефолтное состояние")


@router.callback_query(F.data == f"{PREFIX}:save")
async def climb_save(
    callback: CallbackQuery,
    state: FSMContext,
    climbing: ClimbingRepo,
) -> None:
    from_user = callback.from_user
    draft = await draft_from_state(state)
    if from_user is None or draft is None:
        await callback.answer("Начните с /climb", show_alert=True)
        return

    logger.info("Обработчик /climb: сохраняю запись в YDB")
    await climbing.insert(
        record_id=str(uuid.uuid4()),
        telegram_id=from_user.id,
        name=draft.kind,
        training_date=draft.training_date,
        details=draft.details,
    )
    await state.clear()
    text = confirm_text(draft.kind, draft.training_date, details=draft.details)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"{text}\n\n`✓ сохранено`",
            parse_mode="Markdown",
        )
        await send_ready_prompt(callback.message, state)
    await callback.answer()
    logger.info(
        "Тренировка сохранена: telegram_id=%s, name=%s, training_date=%s",
        from_user.id,
        draft.kind,
        draft.training_date.isoformat(),
    )

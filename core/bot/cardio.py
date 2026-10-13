from __future__ import annotations

import logging
import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import CardioRepo
from bot.ready import send_ready_prompt
from bot.send import answer
from bot.states import Cardio
from bot.training import (
    DATE_PROMPT,
    DETAILS_PROMPT,
    DISTANCE_PROMPT,
    DISTANCE_PROMPT_RETRY,
    cancel_training,
    confirm_keyboard,
    confirm_text,
    draft_from_state,
    parse_date,
    parse_distance,
    today,
)

router = Router(name="cardio")
logger = logging.getLogger(__name__)

PREFIX = "cardio"
KIND_BY_COMMAND = {
    "run": "Бег",
    "velo": "Велосипед",
}
START_HINT = "Начните с /run или /velo"


async def _start_cardio(message: Message, state: FSMContext, kind: str) -> None:
    logger.info("Обработчик cardio: запрос дистанции, kind=%s", kind)
    await state.clear()
    await state.set_state(Cardio.waiting_distance)
    await state.update_data(kind=kind)
    await answer(message, DISTANCE_PROMPT)


@router.message(Command("run"))
async def cmd_run(message: Message, state: FSMContext) -> None:
    await _start_cardio(message, state, KIND_BY_COMMAND["run"])


@router.message(Command("velo"))
async def cmd_velo(message: Message, state: FSMContext) -> None:
    await _start_cardio(message, state, KIND_BY_COMMAND["velo"])


@router.message(Cardio.waiting_distance, F.text, ~F.text.startswith("/"))
async def cardio_distance_entered(message: Message, state: FSMContext) -> None:
    distance = parse_distance(message.text or "")
    if distance is None:
        logger.info("Обработчик cardio: дистанция не подходит под формат")
        await answer(message, DISTANCE_PROMPT_RETRY)
        return

    data = await state.get_data()
    kind = data.get("kind")
    if not isinstance(kind, str):
        await state.clear()
        await answer(message, START_HINT)
        return

    training_date = today()
    await state.set_state(Cardio.confirm)
    await state.update_data(
        distance=distance,
        training_date=training_date.isoformat(),
        details=None,
    )
    text = confirm_text(kind, training_date, distance=distance)
    await answer(message, text, reply_markup=confirm_keyboard(PREFIX))
    logger.info("Обработчик cardio: черновик %s", text)


@router.message(Cardio.waiting_distance, ~F.text.startswith("/"))
async def cardio_distance_expected(message: Message) -> None:
    await answer(message, DISTANCE_PROMPT_RETRY)


@router.callback_query(F.data == f"{PREFIX}:date")
async def cardio_ask_date(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await draft_from_state(state)
    if draft is None or draft.distance is None:
        await callback.answer(START_HINT, show_alert=True)
        return

    await state.set_state(Cardio.waiting_date)
    if isinstance(callback.message, Message):
        await answer(callback.message, DATE_PROMPT)
    await callback.answer()
    logger.info("Обработчик cardio: запрос даты")


@router.message(Cardio.waiting_date, F.text, ~F.text.startswith("/"))
async def cardio_date_entered(message: Message, state: FSMContext) -> None:
    parsed = parse_date(message.text or "")
    if parsed is None:
        logger.info("Обработчик cardio: дата не подходит под формат")
        await answer(message, DATE_PROMPT)
        return

    draft = await draft_from_state(state)
    if draft is None or draft.distance is None:
        await state.clear()
        await answer(message, START_HINT)
        return

    await state.set_state(Cardio.confirm)
    await state.update_data(training_date=parsed.isoformat())
    text = confirm_text(
        draft.kind,
        parsed,
        distance=draft.distance,
        details=draft.details,
    )
    await answer(message, text, reply_markup=confirm_keyboard(PREFIX))
    logger.info("Обработчик cardio: черновик с датой %s", text)


@router.message(Cardio.waiting_date, ~F.text.startswith("/"))
async def cardio_date_expected(message: Message) -> None:
    await answer(message, DATE_PROMPT)


@router.callback_query(F.data == f"{PREFIX}:details")
async def cardio_ask_details(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await draft_from_state(state)
    if draft is None or draft.distance is None:
        await callback.answer(START_HINT, show_alert=True)
        return

    await state.set_state(Cardio.waiting_details)
    if isinstance(callback.message, Message):
        await answer(callback.message, DETAILS_PROMPT)
    await callback.answer()
    logger.info("Обработчик cardio: запрос подробностей")


@router.message(Cardio.waiting_details, F.text, ~F.text.startswith("/"))
async def cardio_details_entered(message: Message, state: FSMContext) -> None:
    details = (message.text or "").strip()
    if not details:
        await answer(message, DETAILS_PROMPT)
        return

    draft = await draft_from_state(state)
    if draft is None or draft.distance is None:
        await state.clear()
        await answer(message, START_HINT)
        return

    await state.set_state(Cardio.confirm)
    await state.update_data(details=details)
    text = confirm_text(
        draft.kind,
        draft.training_date,
        distance=draft.distance,
        details=details,
    )
    await answer(message, text, reply_markup=confirm_keyboard(PREFIX))
    logger.info("Обработчик cardio: черновик с подробностями")


@router.message(Cardio.waiting_details, ~F.text.startswith("/"))
async def cardio_details_expected(message: Message) -> None:
    await answer(message, DETAILS_PROMPT)


@router.callback_query(F.data == f"{PREFIX}:cancel")
async def cardio_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await cancel_training(callback, state)
    logger.info("Обработчик cardio: отмена, возврат в дефолтное состояние")


@router.callback_query(F.data == f"{PREFIX}:save")
async def cardio_save(
    callback: CallbackQuery,
    state: FSMContext,
    cardio: CardioRepo,
) -> None:
    from_user = callback.from_user
    draft = await draft_from_state(state)
    if from_user is None or draft is None or draft.distance is None:
        await callback.answer(START_HINT, show_alert=True)
        return

    logger.info("Обработчик cardio: сохраняю запись в YDB")
    await cardio.insert(
        record_id=str(uuid.uuid4()),
        telegram_id=from_user.id,
        name=draft.kind,
        distance=float(draft.distance),
        training_date=draft.training_date,
        details=draft.details,
    )
    await state.clear()
    text = confirm_text(
        draft.kind,
        draft.training_date,
        distance=draft.distance,
        details=draft.details,
    )
    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"{text}\n\n`✓ сохранено`", parse_mode="Markdown",)
        await send_ready_prompt(callback.message, state)
    await callback.answer()
    logger.info(
        "Кардио сохранено: telegram_id=%s, name=%s, distance=%s, training_date=%s",
        from_user.id,
        draft.kind,
        draft.distance,
        draft.training_date.isoformat(),
    )

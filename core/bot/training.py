from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.months import MONTHS_GENITIVE
from bot.ready import send_ready_prompt

TZ = ZoneInfo("Europe/Moscow")
DATE_PROMPT = "введите дату в формате ДД.ММ.ГГГГ"
DETAILS_PROMPT = "Введите подробности о тренировке"
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
DISTANCE_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
DISTANCE_PROMPT = "Отправьте дистанцию в километрах одной цифрой"
DISTANCE_PROMPT_RETRY = (
    "Отправьте дистанцию в километрах одной цифрой "
    "(допустимо дробное значение с разделителем точкой или запятой)"
)


@dataclass(slots=True, frozen=True)
class TrainingDraft:
    kind: str
    training_date: date
    details: str | None = None
    distance: str | None = None


def today() -> date:
    return datetime.now(TZ).date()


def format_date(value: date) -> str:
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]}"


def parse_date(text: str) -> date | None:
    raw = text.strip()
    if DATE_RE.fullmatch(raw) is None:
        return None
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_distance(text: str) -> str | None:
    raw = (text or "").strip()
    if DISTANCE_RE.fullmatch(raw) is None:
        return None
    return raw.replace(",", ".")


def confirm_text(
    kind: str,
    training_date: date,
    *,
    distance: str | None = None,
    details: str | None = None,
) -> str:
    if distance is not None:
        text = f"{kind} {distance} км, {format_date(training_date)}"
    else:
        text = f"{kind}, {format_date(training_date)}"
    if details:
        text = f"{text}, {details}"
    return text


def confirm_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="отменить", callback_data=f"{prefix}:cancel"),
                InlineKeyboardButton(text="изменить дату", callback_data=f"{prefix}:date"),
            ],
            [
                InlineKeyboardButton(
                    text="добавить подробности",
                    callback_data=f"{prefix}:details",
                ),
                InlineKeyboardButton(text="сохранить", callback_data=f"{prefix}:save"),
            ],
        ]
    )


async def draft_from_state(state: FSMContext) -> TrainingDraft | None:
    data = await state.get_data()
    kind = data.get("kind")
    raw_date = data.get("training_date")
    if not isinstance(kind, str) or not isinstance(raw_date, str):
        return None
    try:
        training_date = date.fromisoformat(raw_date)
    except ValueError:
        return None
    raw_details = data.get("details")
    details = raw_details if isinstance(raw_details, str) and raw_details else None
    raw_distance = data.get("distance")
    distance = raw_distance if isinstance(raw_distance, str) and raw_distance else None
    return TrainingDraft(
        kind=kind,
        training_date=training_date,
        details=details,
        distance=distance,
    )


async def cancel_training(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await send_ready_prompt(callback.message, state)
    await callback.answer()

from __future__ import annotations

import calendar
import html
import logging
from collections import defaultdict
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import CardioRepo, ClimbingRepo, TrainingEntry
from bot.months import MONTHS, MONTHS_GENITIVE
from bot.ready import send_ready_prompt
from bot.send import answer
from bot.training import today

router = Router(name="last")
logger = logging.getLogger(__name__)

PREFIX = "last"
PERIODS = (
    ("today", "сегодня"),
    ("week", "неделя"),
    ("month", "месяц"),
)
PERIOD_CODES = {code for code, _ in PERIODS}
WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


def _period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label, callback_data=f"{PREFIX}:{code}")
                for code, label in PERIODS
            ]
        ]
    )


def _result_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"{PREFIX}:{code}")
        for code, label in PERIODS
        if code != current
    ]
    buttons.append(InlineKeyboardButton(text="завершить", callback_data=f"{PREFIX}:done"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _week_range(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def _month_range(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    last_day = calendar.monthrange(day.year, day.month)[1]
    return start, day.replace(day=last_day)


def _format_distance(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g} км"


def _format_entry(entry: TrainingEntry) -> str:
    name = html.escape(entry.name)
    if entry.distance is not None:
        line = f"{name} {_format_distance(entry.distance)}"
    else:
        line = name
    if entry.details:
        line = f"{line}, {html.escape(entry.details)}"
    return line


def _format_day_heading(day: date) -> str:
    weekday = WEEKDAYS[day.weekday()]
    month = MONTHS_GENITIVE[day.month - 1]
    return f"<code>{weekday}, {day.day} {month}</code>"


def _sort_key(entry: TrainingEntry) -> tuple:
    created = entry.created_at
    return (entry.training_date, created is None, str(created or ""))


def format_today(entries: list[TrainingEntry]) -> str:
    lines = ["<b>Сегодня</b>"]
    if not entries:
        lines.append("Нет тренировок")
        return "\n".join(lines)
    for entry in sorted(entries, key=_sort_key):
        lines.append(_format_entry(entry))
    return "\n".join(lines)


def format_by_days(entries: list[TrainingEntry]) -> str:
    if not entries:
        return "Нет тренировок"

    by_day: dict[date, list[TrainingEntry]] = defaultdict(list)
    for entry in entries:
        by_day[entry.training_date].append(entry)

    blocks: list[str] = []
    for day in sorted(by_day):
        day_lines = [_format_day_heading(day)]
        for entry in sorted(by_day[day], key=_sort_key):
            day_lines.append(_format_entry(entry))
        blocks.append("\n".join(day_lines))
    return "\n\n".join(blocks)


async def _load_entries(
    telegram_id: int,
    date_from: date,
    date_to: date,
    climbing: ClimbingRepo,
    cardio: CardioRepo,
) -> list[TrainingEntry]:
    climbing_entries = await climbing.list_between(telegram_id, date_from, date_to)
    cardio_entries = await cardio.list_between(telegram_id, date_from, date_to)
    return [*climbing_entries, *cardio_entries]


@router.message(Command("last"))
async def cmd_last(message: Message, state: FSMContext) -> None:
    logger.info("Обработчик /last: выбор периода")
    await state.clear()
    await answer(message, "Выберите период", reply_markup=_period_keyboard())


@router.callback_query(F.data == f"{PREFIX}:done")
async def last_done(callback: CallbackQuery, state: FSMContext) -> None:
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await send_ready_prompt(callback.message, state)
    await callback.answer()
    logger.info("Обработчик /last: завершение")


@router.callback_query(F.data.startswith(f"{PREFIX}:"))
async def last_period(
    callback: CallbackQuery,
    climbing: ClimbingRepo,
    cardio: CardioRepo,
) -> None:
    period = (callback.data or "").rsplit(":", 1)[-1]
    from_user = callback.from_user
    if from_user is None or period not in PERIOD_CODES:
        await callback.answer()
        return

    day = today()
    if period == "today":
        date_from = date_to = day
    elif period == "week":
        date_from, date_to = _week_range(day)
    else:
        date_from, date_to = _month_range(day)

    logger.info(
        "Обработчик /last: период=%s, range=%s..%s",
        period,
        date_from.isoformat(),
        date_to.isoformat(),
    )
    entries = await _load_entries(from_user.id, date_from, date_to, climbing, cardio)
    if period == "today":
        text = format_today(entries)
    else:
        title = "На этой неделе" if period == "week" else MONTHS[day.month - 1]
        text = f"<b>{title}</b>\n{format_by_days(entries)}"

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=_result_keyboard(period),
        )
    await callback.answer()

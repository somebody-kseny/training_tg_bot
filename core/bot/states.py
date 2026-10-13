from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    name = State()


class Climb(StatesGroup):
    confirm = State()
    waiting_date = State()
    waiting_details = State()


class Cardio(StatesGroup):
    waiting_distance = State()
    confirm = State()
    waiting_date = State()
    waiting_details = State()


class Delete(StatesGroup):
    waiting_date = State()
    choosing = State()

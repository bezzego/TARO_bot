from aiogram.fsm.state import StatesGroup, State

class BookingState(StatesGroup):
    story = State()
    participants = State()
    photos = State()
    questions = State()
    phone = State()
    select_date = State()
    select_time = State()
    waiting_receipt = State()

class AdminState(StatesGroup):
    adding_slot = State()
    deleting_slot = State()
    unlocking_slot = State()
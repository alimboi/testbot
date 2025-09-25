from aiogram.dispatcher.filters.state import State, StatesGroup

class StudentStates(StatesGroup):

    Choosing = State()
    
    EnteringName = State()
    
    ConfirmingName = State()
    
    Understanding = State()
    
    Answering = State()

class AdminStates(StatesGroup):

    Confirming = State()
    

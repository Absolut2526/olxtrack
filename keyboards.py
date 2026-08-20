from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Додати новий пошук")],
            [KeyboardButton(text="📋 Мої підписки"), KeyboardButton(text="ℹ️ Допомога")]
        ],
        resize_keyboard=True
    )

def get_skip_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Пропустити")],
            [KeyboardButton(text="❌ Скасувати")]
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Скасувати")]
        ],
        resize_keyboard=True
    )

def get_subscription_actions_keyboard(sub_id: int, is_active: bool) -> InlineKeyboardMarkup:
    status_btn_text = "⏸ Пауза" if is_active else "▶️ Відновити"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Змінити ціну", callback_data=f"editprice_{sub_id}"),
                InlineKeyboardButton(text=status_btn_text, callback_data=f"toggle_{sub_id}")
            ],
            [
                InlineKeyboardButton(text="🗑 Видалити", callback_data=f"delete_{sub_id}"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_list")
            ]
        ]
    )

def get_offer_link_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Відкрити на OLX", url=url)]
        ]
    )

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from keyboards import (
    get_main_keyboard,
    get_skip_cancel_keyboard,
    get_cancel_keyboard,
    get_subscription_actions_keyboard,
)
import database as db
import olx_parser

logger = logging.getLogger(__name__)
router = Router()

class AddSubscription(StatesGroup):
    waiting_for_query = State()
    waiting_for_min_price = State()
    waiting_for_max_price = State()

class EditPrice(StatesGroup):
    waiting_for_min_price = State()
    waiting_for_max_price = State()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        f"👋 <b>Привіт, {message.from_user.first_name}!</b>\n\n"
        "Я бот для моніторингу найсвіжіших оголошень на <b>OLX Україна</b>.\n\n"
        "⚡ <b>Особливості:</b>\n"
        "• Надсилає <b>тільки щойно викладені</b> оголошення.\n"
        "• Автоматично розуміє синоніми (<i>iPhone 14 / айфон 14</i>).\n"
        "• Гнучке налаштування цін для кожної підписки.\n\n"
        "Оберіть дію в меню нижче 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.message(F.text == "ℹ️ Допомога")
@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    help_text = (
        "📖 <b>Інструкція з використання:</b>\n\n"
        "• <b>🔍 Додати новий пошук</b> — створення нової підписки на товар із фільтром цін.\n"
        "• <b>📋 Мої підписки</b> — перегляд, зміна ціни, зупинка або видалення ваших пошуків.\n\n"
        "⚡ <i>Бот моніторить OLX і надсилає повідомлення в момент публікації нового товару!</i>"
    )
    await message.answer(help_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.message(F.text == "❌ Скасувати")
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Дію скасовано.", reply_markup=get_main_keyboard())

# --- FSM: Створення підписки ---

@router.message(F.text == "🔍 Додати новий пошук")
@router.message(Command("add"))
async def start_add_subscription(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddSubscription.waiting_for_query)
    await message.answer(
        "🔎 Введіть назву товару або пошуковий запит:\n"
        "<i>(наприклад: iPhone 14, MacBook Pro M1, Велосипед Trek)</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AddSubscription.waiting_for_query)
async def process_query(message: Message, state: FSMContext):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Запит занадто короткий. Спробуйте ще раз:")
        return

    await state.update_data(query=query)
    await state.set_state(AddSubscription.waiting_for_min_price)
    await message.answer(
        f"💵 Введіть <b>мінімальну ціну</b> в грн або натисніть <b>⏭ Пропустити</b>:",
        reply_markup=get_skip_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AddSubscription.waiting_for_min_price)
async def process_min_price(message: Message, state: FSMContext):
    text = message.text.strip()
    min_price = None

    if text != "⏭ Пропустити":
        try:
            min_price = float(text.replace(" ", "").replace(",", "."))
            if min_price < 0:
                raise ValueError()
        except ValueError:
            await message.answer("⚠️ Будь ласка, введіть коректне число або натисніть <b>⏭ Пропустити</b>:", parse_mode="HTML")
            return

    await state.update_data(min_price=min_price)
    await state.set_state(AddSubscription.waiting_for_max_price)
    await message.answer(
        f"💵 Введіть <b>максимальну ціну</b> в грн або натисніть <b>⏭ Пропустити</b>:",
        reply_markup=get_skip_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AddSubscription.waiting_for_max_price)
async def process_max_price(message: Message, state: FSMContext):
    text = message.text.strip()
    max_price = None

    if text != "⏭ Пропустити":
        try:
            max_price = float(text.replace(" ", "").replace(",", "."))
            if max_price < 0:
                raise ValueError()
        except ValueError:
            await message.answer("⚠️ Будь ласка, введіть коректне число або натисніть <b>⏭ Пропустити</b>:", parse_mode="HTML")
            return

    data = await state.get_data()
    query = data["query"]
    min_price = data.get("min_price")

    if min_price is not None and max_price is not None and min_price > max_price:
        await message.answer("⚠️ Мінімальна ціна не може бути більшою за максимальну. Спробуйте ще раз ввести максимальну ціну:")
        return

    sub_id = await db.add_subscription(
        user_id=message.from_user.id,
        query=query,
        min_price=min_price,
        max_price=max_price
    )
    await state.clear()

    price_info = "Будь-яка"
    if min_price and max_price:
        price_info = f"від {min_price:g} до {max_price:g} грн"
    elif min_price:
        price_info = f"від {min_price:g} грн"
    elif max_price:
        price_info = f"до {max_price:g} грн"

    msg = (
        f"✅ <b>Підписку успішно додано!</b>\n\n"
        f"🔍 <b>Запит:</b> {query}\n"
        f"💰 <b>Ціна:</b> {price_info}\n\n"
        f"⏳ <i>Фіксуємо поточні оголошення...</i>"
    )
    status_msg = await message.answer(msg, reply_markup=get_main_keyboard(), parse_mode="HTML")

    existing_offers = await olx_parser.fetch_olx_offers(query=query, min_price=min_price, max_price=max_price, limit=50)
    if existing_offers:
        offer_ids = [o.id for o in existing_offers]
        await db.mark_offers_seen_batch(sub_id, offer_ids)

    await status_msg.edit_text(
        f"✅ <b>Підписку активовано!</b>\n\n"
        f"🔍 <b>Запит:</b> {query}\n"
        f"💰 <b>Ціна:</b> {price_info}\n\n"
        f"✨ Бот надсилатиме <b>виключно свіжі оголошення</b>! 🚀",
        parse_mode="HTML"
    )

# --- FSM: Зміна ціни підписки ---

@router.callback_query(F.data.startswith("editprice_"))
async def callback_start_edit_price(call: CallbackQuery, state: FSMContext):
    sub_id = int(call.data.split("_")[1])
    sub = await db.get_subscription_by_id(sub_id, call.from_user.id)
    if not sub:
        await call.answer("⚠️ Підписку не знайдено", show_alert=True)
        return

    await state.set_state(EditPrice.waiting_for_min_price)
    await state.update_data(sub_id=sub_id, query=sub["query"])

    await call.message.answer(
        f"✏️ <b>Зміна ціни для:</b> {sub['query']}\n\n"
        f"Введіть нову <b>мінімальну ціну</b> в грн або натисніть <b>⏭ Пропустити</b>:",
        reply_markup=get_skip_cancel_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()

@router.message(EditPrice.waiting_for_min_price)
async def process_edit_min_price(message: Message, state: FSMContext):
    text = message.text.strip()
    min_price = None

    if text != "⏭ Пропустити":
        try:
            min_price = float(text.replace(" ", "").replace(",", "."))
            if min_price < 0:
                raise ValueError()
        except ValueError:
            await message.answer("⚠️ Будь ласка, введіть коректне число або натисніть <b>⏭ Пропустити</b>:", parse_mode="HTML")
            return

    await state.update_data(min_price=min_price)
    await state.set_state(EditPrice.waiting_for_max_price)
    await message.answer(
        f"💵 Введіть нову <b>максимальну ціну</b> в грн або натисніть <b>⏭ Пропустити</b>:",
        reply_markup=get_skip_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(EditPrice.waiting_for_max_price)
async def process_edit_max_price(message: Message, state: FSMContext):
    text = message.text.strip()
    max_price = None

    if text != "⏭ Пропустити":
        try:
            max_price = float(text.replace(" ", "").replace(",", "."))
            if max_price < 0:
                raise ValueError()
        except ValueError:
            await message.answer("⚠️ Будь ласка, введіть коректне число або натисніть <b>⏭ Пропустити</b>:", parse_mode="HTML")
            return

    data = await state.get_data()
    sub_id = data["sub_id"]
    query = data["query"]
    min_price = data.get("min_price")

    if min_price is not None and max_price is not None and min_price > max_price:
        await message.answer("⚠️ Мінімальна ціна не може бути більшою за максимальну. Спробуйте ще раз ввести максимальну ціну:")
        return

    # Оновлення ціни в базі
    await db.update_subscription_price(sub_id, message.from_user.id, min_price, max_price)
    await state.clear()

    price_info = "Будь-яка"
    if min_price and max_price:
        price_info = f"від {min_price:g} до {max_price:g} грн"
    elif min_price:
        price_info = f"від {min_price:g} грн"
    elif max_price:
        price_info = f"до {max_price:g} грн"

    await message.answer(
        f"✅ <b>Ціну успішно оновлено!</b>\n\n"
        f"📌 <b>Запит:</b> {query}\n"
        f"💰 <b>Нова ціна:</b> {price_info}",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# --- Список підписок ---

@router.message(F.text == "📋 Мої підписки")
@router.message(Command("list"))
async def list_subscriptions(message: Message, state: FSMContext):
    await state.clear()
    subs = await db.get_user_subscriptions(message.from_user.id)
    if not subs:
        await message.answer(
            "📋 У вас ще немає активних підписок.\n"
            "Натисніть <b>🔍 Додати новий пошук</b>, щоб створити першу!",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        return

    await message.answer(f"📋 <b>Ваші підписки ({len(subs)}):</b>", parse_mode="HTML")

    for sub in subs:
        status_icon = "🟢 Активна" if sub["is_active"] else "⏸ На паузі"
        price_info = "Будь-яка"
        if sub["min_price"] and sub["max_price"]:
            price_info = f"{sub['min_price']:g} - {sub['max_price']:g} грн"
        elif sub["min_price"]:
            price_info = f"від {sub['min_price']:g} грн"
        elif sub["max_price"]:
            price_info = f"до {sub['max_price']:g} грн"

        text = (
            f"📌 <b>{sub['query']}</b>\n"
            f"💰 Ціна: {price_info}\n"
            f"Статус: {status_icon}\n"
            f"Створено: {sub['created_at'][:16].replace('T', ' ')}"
        )
        await message.answer(
            text,
            reply_markup=get_subscription_actions_keyboard(sub["id"], bool(sub["is_active"])),
            parse_mode="HTML"
        )

# --- Callback обробники (Кнопки) ---

@router.callback_query(F.data.startswith("toggle_"))
async def callback_toggle_sub(call: CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    new_status = await db.toggle_subscription(sub_id, call.from_user.id)
    if new_status is None:
        await call.answer("⚠️ Підписку не знайдено", show_alert=True)
        return

    sub = await db.get_subscription_by_id(sub_id, call.from_user.id)
    status_icon = "🟢 Активна" if new_status else "⏸ На паузі"
    price_info = "Будь-яка"
    if sub["min_price"] and sub["max_price"]:
        price_info = f"{sub['min_price']:g} - {sub['max_price']:g} грн"
    elif sub["min_price"]:
        price_info = f"від {sub['min_price']:g} грн"
    elif sub["max_price"]:
        price_info = f"до {sub['max_price']:g} грн"

    text = (
        f"📌 <b>{sub['query']}</b>\n"
        f"💰 Ціна: {price_info}\n"
        f"Статус: {status_icon}\n"
        f"Створено: {sub['created_at'][:16].replace('T', ' ')}"
    )
    await call.message.edit_text(text, reply_markup=get_subscription_actions_keyboard(sub_id, bool(new_status)), parse_mode="HTML")
    await call.answer("Статус оновлено!")

@router.callback_query(F.data.startswith("delete_"))
async def callback_delete_sub(call: CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    deleted = await db.delete_subscription(sub_id, call.from_user.id)
    if deleted:
        await call.message.edit_text("🗑 <b>Підписку видалено.</b>", parse_mode="HTML")
        await call.answer("Видалено!")
    else:
        await call.answer("Помилка видалення або вже видалено.", show_alert=True)

@router.callback_query(F.data == "back_to_list")
async def callback_back_to_list(call: CallbackQuery, state: FSMContext):
    await call.message.delete()
    await list_subscriptions(call.message, state)
    await call.answer()

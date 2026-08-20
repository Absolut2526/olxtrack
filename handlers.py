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
    get_seller_type_keyboard,
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
    waiting_for_seller_type = State()

class EditPrice(StatesGroup):
    waiting_for_min_price = State()
    waiting_for_max_price = State()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        f"👋 <b>Привіт, {message.from_user.first_name}!</b>\n\n"
        "Я бот для моніторингу найсвіжіших оголошень на <b>OLX Україна</b>.\n\n"
        "⚡ <b>Можливості:</b>\n"
        "• 🆕 Тільки нові публікації (без спаму та старих піднятих оголошень).\n"
        "• 🔥 <b>Розумна оцінка цін</b> (знаходжу гарячі пропозиції нижче ринку!).\n"
        "• 📊 <b>Аналітика ринку</b> (середня, мінімальна та медіанна ціна товару).\n"
        "• 📉 <b>Відстеження зниження ціни</b> від продавців.\n"
        "• 👤 <b>Фільтр продавців</b> (тільки приватні або всі).\n\n"
        "Оберіть дію в меню нижче 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.message(F.text == "ℹ️ Допомога")
@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    help_text = (
        "📖 <b>Інструкція:</b>\n\n"
        "• <b>🔍 Додати новий пошук</b> — створення нової підписки з фільтрами цін та продавців.\n"
        "• <b>📋 Мої підписки</b> — перегляд списку, аналітика ринку 📊, зміна ціни ✏️, пауза та видалення.\n\n"
        "🔥 <i>Бот автоматично сповістить про нові товари та покаже плашку «🔥 ГАРЯЧА ЦІНА», якщо товар суттєво дешевший за ринок!</i>"
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
    min_price = data.get("min_price")

    if min_price is not None and max_price is not None and min_price > max_price:
        await message.answer("⚠️ Мінімальна ціна не може бути більшою за максимальну. Спробуйте ще раз ввести максимальну ціну:")
        return

    await state.update_data(max_price=max_price)
    await state.set_state(AddSubscription.waiting_for_seller_type)
    await message.answer(
        "👤 Оберіть тип продавця:",
        reply_markup=get_seller_type_keyboard()
    )

@router.message(AddSubscription.waiting_for_seller_type)
async def process_seller_type(message: Message, state: FSMContext):
    text = message.text.strip()
    only_private = 1 if "Тільки приватні" in text else 0

    data = await state.get_data()
    query = data["query"]
    min_price = data.get("min_price")
    max_price = data.get("max_price")

    sub_id = await db.add_subscription(
        user_id=message.from_user.id,
        query=query,
        min_price=min_price,
        max_price=max_price,
        only_private=only_private
    )
    await state.clear()

    price_info = "Будь-яка"
    if min_price and max_price:
        price_info = f"від {min_price:g} до {max_price:g} грн"
    elif min_price:
        price_info = f"від {min_price:g} грн"
    elif max_price:
        price_info = f"до {max_price:g} грн"

    seller_info = "👤 Тільки приватні особи" if only_private else "👥 Всі продавці"

    msg = (
        f"✅ <b>Підписку успішно додано!</b>\n\n"
        f"🔍 <b>Запит:</b> {query}\n"
        f"💰 <b>Ціна:</b> {price_info}\n"
        f"🏷 <b>Продавці:</b> {seller_info}\n\n"
        f"⏳ <i>Аналізуємо ринок та фіксуємо оголошення...</i>"
    )
    status_msg = await message.answer(msg, reply_markup=get_main_keyboard(), parse_mode="HTML")

    existing_offers = await olx_parser.fetch_olx_offers(
        query=query,
        min_price=min_price,
        max_price=max_price,
        only_private=bool(only_private),
        limit=50
    )
    if existing_offers:
        offers_data = [(o.id, o.price_val) for o in existing_offers]
        await db.mark_offers_seen_batch(sub_id, offers_data)

    stats = await olx_parser.calculate_market_stats(query, min_price=min_price, max_price=max_price)
    stats_text = ""
    if stats:
        stats_text = f"\n\n📊 <b>Середня ціна на ринку:</b> ~{int(stats.median_price):,} грн"

    await status_msg.edit_text(
        f"✅ <b>Підписку активовано!</b>\n\n"
        f"🔍 <b>Запит:</b> {query}\n"
        f"💰 <b>Ціна:</b> {price_info}\n"
        f"🏷 <b>Продавці:</b> {seller_info}"
        f"{stats_text}\n\n"
        f"✨ Бот надсилатиме <b>виключно свіжі оголошення</b> та виділятиме <b>гарячі пропозиції</b>! 🚀",
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
        await message.answer("⚠️ Мінімальна ціна не може бути більшою за максимальну. Спробуйте ще раз:")
        return

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

# --- Аналітика ринку ---

@router.callback_query(F.data.startswith("analytics_"))
async def callback_show_analytics(call: CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    sub = await db.get_subscription_by_id(sub_id, call.from_user.id)
    if not sub:
        await call.answer("⚠️ Підписку не знайдено", show_alert=True)
        return

    await call.answer("📊 Збираємо ринкові дані...")
    
    stats = await olx_parser.calculate_market_stats(
        query=sub["query"],
        min_price=sub["min_price"],
        max_price=sub["max_price"]
    )

    if not stats:
        await call.message.answer(
            f"📊 <b>Аналітика для «{sub['query']}»:</b>\n\n"
            "Недостатньо активних оголошень для формування точної статистики цін.",
            parse_mode="HTML"
        )
        return

    hot_deal_threshold = int(stats.median_price * 0.8)

    text = (
        f"📊 <b>Ринкова аналітика для «{sub['query']}»:</b>\n\n"
        f"📦 <b>Проаналізовано оголошень:</b> {stats.count} шт.\n"
        f"🎯 <b>Медіанна / Середня ціна:</b> ~{int(stats.median_price):,} грн\n"
        f"📉 <b>Найдешевше на ринку:</b> {int(stats.min_price):,} грн\n"
        f"📈 <b>Найдорожче на ринку:</b> {int(stats.max_price):,} грн\n\n"
        f"🔥 <b>Поріг вигідної угоди:</b> нижче <b>{hot_deal_threshold:,} грн</b> (від -20% від ринку)"
    )
    await call.message.answer(text, parse_mode="HTML")

# --- Список підписок ---

def format_sub_card(sub: dict) -> str:
    status_icon = "🟢 Активна" if sub["is_active"] else "⏸ На паузі"
    seller_icon = "👤 Тільки приватні" if sub.get("only_private") else "👥 Всі продавці"
    price_info = "Будь-яка"
    if sub["min_price"] and sub["max_price"]:
        price_info = f"{sub['min_price']:g} - {sub['max_price']:g} грн"
    elif sub["min_price"]:
        price_info = f"від {sub['min_price']:g} грн"
    elif sub["max_price"]:
        price_info = f"до {sub['max_price']:g} грн"

    return (
        f"📌 <b>{sub['query']}</b>\n"
        f"💰 Ціна: {price_info}\n"
        f"🏷 Продавці: {seller_icon}\n"
        f"Статус: {status_icon}\n"
        f"Створено: {sub['created_at'][:16].replace('T', ' ')}"
    )

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
        text = format_sub_card(sub)
        await message.answer(
            text,
            reply_markup=get_subscription_actions_keyboard(
                sub["id"],
                bool(sub["is_active"]),
                bool(sub.get("only_private", 0))
            ),
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
    text = format_sub_card(sub)
    await call.message.edit_text(
        text,
        reply_markup=get_subscription_actions_keyboard(
            sub_id,
            bool(new_status),
            bool(sub.get("only_private", 0))
        ),
        parse_mode="HTML"
    )
    await call.answer("Статус оновлено!")

@router.callback_query(F.data.startswith("togglepriv_"))
async def callback_toggle_private(call: CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    new_priv = await db.toggle_private_filter(sub_id, call.from_user.id)
    if new_priv is None:
        await call.answer("⚠️ Підписку не знайдено", show_alert=True)
        return

    sub = await db.get_subscription_by_id(sub_id, call.from_user.id)
    text = format_sub_card(sub)
    await call.message.edit_text(
        text,
        reply_markup=get_subscription_actions_keyboard(
            sub_id,
            bool(sub["is_active"]),
            bool(new_priv)
        ),
        parse_mode="HTML"
    )
    await call.answer("Фільтр продавців змінено!")

@router.callback_query(F.data.startswith("delete_"))
async def callback_delete_sub(call: CallbackQuery):
    sub_id = int(call.data.split("_")[1])
    deleted = await db.delete_subscription(sub_id, call.from_user.id)
    if deleted:
        await call.message.edit_text("🗑 <b>Підписку видалено.</b>", parse_mode="HTML")
        await call.answer("Видалено!")
    else:
        await call.answer("Помилка видалення.", show_alert=True)

@router.callback_query(F.data == "back_to_list")
async def callback_back_to_list(call: CallbackQuery, state: FSMContext):
    await call.message.delete()
    await list_subscriptions(call.message, state)
    await call.answer()

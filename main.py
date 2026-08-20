import asyncio
import logging
import sys
import os
from datetime import datetime, timezone
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
import database as db
import olx_parser
from handlers import router
from keyboards import get_offer_link_keyboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

async def handle_healthcheck(request):
    return web.Response(text="OLX Monitor Bot is running OK!", status=200)

async def start_health_server():
    """Lightweight HTTP server for Render Web Service health checks."""
    port = int(os.getenv("PORT", "10000"))
    app = web.Application()
    app.router.add_route("*", "/", handle_healthcheck)
    app.router.add_route("*", "/health", handle_healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck server listening on 0.0.0.0:{port}")
    return runner

# Cache market stats per query to avoid spamming the API
market_stats_cache = {}

async def get_cached_market_stats(query: str, min_p, max_p):
    key = f"{query}_{min_p}_{max_p}"
    now = datetime.now()
    if key in market_stats_cache:
        stats, timestamp = market_stats_cache[key]
        if (now - timestamp).total_seconds() < 3600: # 1 hour cache
            return stats
    
    stats = await olx_parser.calculate_market_stats(query, min_p, max_p)
    if stats:
        market_stats_cache[key] = (stats, now)
    return stats

async def monitor_olx_task(bot: Bot):
    """
    Background task that periodically checks OLX for strictly fresh ads, price drops, and hot deals.
    """
    logger.info(f"Starting OLX monitor background task (Interval: {config.CHECK_INTERVAL_SECONDS}s)...")
    await asyncio.sleep(5)

    while True:
        try:
            active_subs = await db.get_all_active_subscriptions()
            if not active_subs:
                await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)
                continue

            now_utc = datetime.now(timezone.utc)

            for sub in active_subs:
                sub_id = sub["id"]
                user_id = sub["user_id"]
                query = sub["query"]
                min_price = sub["min_price"]
                max_price = sub["max_price"]
                only_private = bool(sub.get("only_private", 0))
                sub_created_at_str = sub.get("created_at")

                sub_created_dt = None
                if sub_created_at_str:
                    try:
                        sub_created_dt = datetime.fromisoformat(sub_created_at_str).astimezone(timezone.utc)
                    except Exception:
                        pass

                offers = await olx_parser.fetch_olx_offers(
                    query=query,
                    min_price=min_price,
                    max_price=max_price,
                    only_private=only_private,
                    limit=30
                )

                # Get market stats for query
                stats = await get_cached_market_stats(query, min_price, max_price)

                for offer in reversed(offers):
                    seen, old_price = await db.get_seen_offer(sub_id, offer.id)

                    # --- 1. PRICE DROP CHECK FOR EXISTING OFFERS ---
                    if seen:
                        if old_price is not None and offer.price_val is not None and offer.price_val < old_price:
                            discount = old_price - offer.price_val
                            pct = (discount / old_price) * 100
                            caption = (
                                f"📉 <b>ЗНИЖЕННЯ ЦІНИ! (-{discount:g} грн / -{pct:.0f}%)</b>\n"
                                f"🔍 Пошук: <i>{query}</i>\n\n"
                                f"🏷 <b>{offer.title}</b>\n"
                                f"💰 Було: <s>{old_price:g} грн</s> ➡️ <b>{offer.price_str}</b>\n"
                                f"📍 <b>Локація:</b> {offer.location}\n"
                            )
                            keyboard = get_offer_link_keyboard(offer.url)

                            try:
                                if offer.photo_url:
                                    await bot.send_photo(
                                        chat_id=user_id,
                                        photo=offer.photo_url,
                                        caption=caption,
                                        reply_markup=keyboard,
                                        parse_mode=ParseMode.HTML
                                    )
                                else:
                                    await bot.send_message(
                                        chat_id=user_id,
                                        text=caption,
                                        reply_markup=keyboard,
                                        parse_mode=ParseMode.HTML
                                    )
                                logger.info(f"Price drop sent for offer {offer.id} ({old_price} -> {offer.price_val})")
                                await asyncio.sleep(0.5)
                            except Exception as send_err:
                                logger.error(f"Failed to send price drop alert to {user_id}: {send_err}")

                            await db.mark_offer_seen(sub_id, offer.id, offer.price_val)
                        continue

                    # --- 2. NEW FRESH OFFER CHECK ---
                    await db.mark_offer_seen(sub_id, offer.id, offer.price_val)

                    if sub_created_dt and offer.created_dt and offer.created_dt < sub_created_dt:
                        continue

                    if offer.created_dt:
                        age_minutes = (now_utc - offer.created_dt).total_seconds() / 60
                        if age_minutes > 60:
                            continue
                        
                        time_label = "щойно" if age_minutes <= 2 else f"{int(age_minutes)} хв тому"
                    else:
                        time_label = "щойно"

                    # Hot deal badge check
                    hot_deal_header = f"🆕 <b>Щойно опубліковано!</b> ({time_label})"
                    price_line = f"💰 <b>Ціна:</b> {offer.price_str}"

                    if stats and stats.median_price and offer.price_val and offer.price_val > 0:
                        diff_pct = (stats.median_price - offer.price_val) / stats.median_price * 100
                        if diff_pct >= 20: # 20% or more below market
                            hot_deal_header = f"🔥 <b>ГАРЯЧА ПРОПОЗИЦІЯ! (-{diff_pct:.0f}% від ринку!)</b> ({time_label})"
                            price_line = f"💰 <b>Ціна:</b> {offer.price_str} <i>(Сер. на OLX: ~{int(stats.median_price):,} грн)</i>"

                    seller_tag = "👤 Приватна особа" if not offer.is_business else "🏢 Бізнес / Магазин"

                    caption = (
                        f"{hot_deal_header}\n"
                        f"🔍 Пошук: <i>{query}</i>\n\n"
                        f"🏷 <b>{offer.title}</b>\n"
                        f"{price_line}\n"
                        f"👤 <b>Продавець:</b> {seller_tag}\n"
                        f"📍 <b>Локація:</b> {offer.location}\n"
                    )

                    keyboard = get_offer_link_keyboard(offer.url)

                    try:
                        if offer.photo_url:
                            await bot.send_photo(
                                chat_id=user_id,
                                photo=offer.photo_url,
                                caption=caption,
                                reply_markup=keyboard,
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            await bot.send_message(
                                chat_id=user_id,
                                text=caption,
                                reply_markup=keyboard,
                                parse_mode=ParseMode.HTML
                            )
                        logger.info(f"Sent new offer {offer.id} ('{offer.title}') to user {user_id}")
                        await asyncio.sleep(0.5)
                    except Exception as send_err:
                        logger.error(f"Failed to send alert to user {user_id}: {send_err}")

                await asyncio.sleep(1.5)

        except Exception as e:
            logger.error(f"Unexpected error in monitor loop: {e}", exc_info=True)

        await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("❌ BOT_TOKEN is not set in environment or .env file!")
        return

    await db.init_db()
    logger.info("Database initialized successfully.")

    web_runner = await start_health_server()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)

    monitor_coro = asyncio.create_task(monitor_olx_task(bot))

    try:
        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    finally:
        monitor_coro.cancel()
        await web_runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

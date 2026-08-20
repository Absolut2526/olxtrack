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
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", handle_healthcheck)
    app.router.add_get("/health", handle_healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck server listening on port {port}")
    return runner

async def monitor_olx_task(bot: Bot):
    """
    Background task that periodically checks OLX for strictly fresh/newly created ads.
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
                    limit=30
                )

                for offer in reversed(offers):
                    seen = await db.is_offer_seen(sub_id, offer.id)
                    if seen:
                        continue

                    # Mark as seen
                    await db.mark_offer_seen(sub_id, offer.id)

                    # Freshness filter: must be after subscription created
                    if sub_created_dt and offer.created_dt and offer.created_dt < sub_created_dt:
                        continue

                    # Filter out old pushed ads (> 60 mins)
                    if offer.created_dt:
                        age_minutes = (now_utc - offer.created_dt).total_seconds() / 60
                        if age_minutes > 60:
                            logger.info(f"Skipping old pushed offer {offer.id} (age: {age_minutes:.1f}m)")
                            continue
                        
                        if age_minutes <= 2:
                            time_label = "щойно"
                        else:
                            time_label = f"{int(age_minutes)} хв тому"
                    else:
                        time_label = "щойно"

                    caption = (
                        f"🆕 <b>Щойно опубліковано!</b> ({time_label})\n"
                        f"🔍 Пошук: <i>{query}</i>\n\n"
                        f"🏷 <b>{offer.title}</b>\n"
                        f"💰 <b>Ціна:</b> {offer.price_str}\n"
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

    # Start healthcheck server for Render
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

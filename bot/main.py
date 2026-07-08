"""Точка входа: запускает Telegram-бота, Discord-бота и HTTP API вместе.

Запуск: python -m bot.main
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import config, db
from bot.api.server import start_api
from bot.ds.bot import start_discord_bot
from bot.tg import notify
from bot.tg.handlers import create_dispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("main")


async def main() -> None:
    await db.init_pool()
    log.info("Database connected, bot tables ensured")

    tg_bot = Bot(
        token=config.TG_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    notify.set_bot(tg_bot)
    dp = create_dispatcher()

    await start_api()

    tasks = [
        asyncio.create_task(dp.start_polling(tg_bot), name="telegram"),
        asyncio.create_task(start_discord_bot(), name="discord"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        await db.close_pool()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down")

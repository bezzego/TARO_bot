import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from handlers import user_handlers, admin_handlers
from scheduler import scheduler
import database

async def main():
    # Configure logging to file and console
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
    )
    # Initialize bot and dispatcher
    bot = Bot(token=config.BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()
    # Set global bot instance for use in other modules
    config.bot = bot
    # Register routers
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)
    # Initialize database
    await database.init_db()
    # Start scheduler for background jobs
    scheduler.start()

    # Shutdown handler for graceful cleanup
    @dp.shutdown()
    async def on_shutdown():
        logging.info("Shutting down...")
        scheduler.shutdown()
        await bot.session.close()
        if database.db:
            await database.db.close()

    logging.info("Bot is starting polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import logging

from bot.factory import close_runtime, get_runtime


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot, dispatcher = await get_runtime()
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await close_runtime()


if __name__ == "__main__":
    asyncio.run(main())

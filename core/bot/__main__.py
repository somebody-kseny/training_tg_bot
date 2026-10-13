from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from aiohttp import web

from bot.config import LISTEN_HOST
from bot.factory import close_runtime, get_runtime, get_settings
from bot.webhook import create_app, install_webhook, remove_webhook


async def run_webhook() -> None:
    settings = get_settings()
    app = await create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=LISTEN_HOST, port=settings.listen_port)
    await site.start()
    logging.info(
        "Webhook слушает %s:%s%s (доступ только с этой машины, снаружи — nginx :443)",
        LISTEN_HOST,
        settings.listen_port,
        settings.webhook_path,
    )
    await install_webhook(settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            break

    try:
        await stop.wait()
    finally:
        try:
            await remove_webhook()
        except Exception:
            logging.exception("Не удалось удалить webhook при остановке")
        await runner.cleanup()
        await close_runtime()


async def run_polling() -> None:
    bot, dispatcher = await get_runtime()
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Webhook удалён — режим long polling")
    try:
        await dispatcher.start_polling(bot)
    finally:
        await close_runtime()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="trens-bot core")
    parser.add_argument(
        "--poll",
        action="store_true",
        help="локальная отладка через long polling вместо webhook",
    )
    args = parser.parse_args()
    if args.poll:
        asyncio.run(run_polling())
    else:
        asyncio.run(run_webhook())


if __name__ == "__main__":
    main()

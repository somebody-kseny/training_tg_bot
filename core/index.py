import logging

logging.getLogger().setLevel(logging.INFO)

from bot.webhook import handler

__all__ = ["handler"]

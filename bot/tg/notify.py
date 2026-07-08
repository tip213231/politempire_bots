"""Отправка 2FA-кодов игрокам в Telegram (используется HTTP API)."""
import logging

from aiogram import Bot

log = logging.getLogger("tg.notify")

_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def send_2fa_code(telegram_id: int, username: str, code: str, ttl_seconds: int) -> bool:
    if _bot is None:
        log.error("TG bot is not set for notifications")
        return False
    try:
        await _bot.send_message(
            telegram_id,
            f"Код входа на сервер для <b>{username}</b>:\n\n"
            f"<code>{code}</code>\n\n"
            f"Введите его в игре командой /2fa {code}\n"
            f"Код действует {ttl_seconds // 60} мин. "
            f"Если это не вы — срочно смените пароль!",
        )
        return True
    except Exception:
        log.exception("Failed to send 2FA code to %s", telegram_id)
        return False

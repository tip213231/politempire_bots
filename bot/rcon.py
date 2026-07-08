"""Выдача/списание DC Coin через RCON: donate give <ник> <сумма> / donate take <ник> <сумма>."""
import asyncio
import logging

import aiomcrcon

from bot import config, db

log = logging.getLogger("rcon")
_lock = asyncio.Lock()


async def _send(command: str) -> str:
    async with _lock:
        client = aiomcrcon.Client(config.RCON_HOST, config.RCON_PORT, config.RCON_PASSWORD)
        try:
            await client.connect(timeout=10)
            response, _ = await client.send_cmd(command, timeout=10)
            return response
        finally:
            try:
                await client.close()
            except Exception:
                pass


async def give_coins(mc_username: str, amount: int, reason: str, actor: str = "system") -> str:
    """Начисляет DC Coin и пишет журнал."""
    if amount <= 0:
        raise ValueError("amount must be > 0")
    response = await _send(f"donate give {mc_username} {amount}")
    await db.execute(
        "INSERT INTO bot_balance_log (mc_username, amount, reason, actor) VALUES (%s, %s, %s, %s)",
        (mc_username, amount, reason, actor),
    )
    log.info("RCON give %s -> %s: %s", amount, mc_username, response)
    return response


async def take_coins(mc_username: str, amount: int, reason: str, actor: str = "system") -> str:
    """Списывает DC Coin и пишет журнал."""
    if amount <= 0:
        raise ValueError("amount must be > 0")
    response = await _send(f"donate take {mc_username} {amount}")
    await db.execute(
        "INSERT INTO bot_balance_log (mc_username, amount, reason, actor) VALUES (%s, %s, %s, %s)",
        (mc_username, -amount, reason, actor),
    )
    log.info("RCON take %s <- %s: %s", amount, mc_username, response)
    return response

"""Логика двухфакторной аутентификации."""
import secrets
from datetime import datetime, timedelta

from bot import config, db


async def is_enabled_for_user(user_id: int) -> bool:
    force = await db.get_setting("force_2fa", "0")
    if force == "1":
        return True
    row = await db.fetchone("SELECT enabled FROM bot_2fa WHERE user_id=%s", (user_id,))
    return bool(row and row["enabled"])


async def set_enabled(user_id: int, enabled: bool) -> None:
    await db.execute(
        "INSERT INTO bot_2fa (user_id, enabled) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)",
        (user_id, 1 if enabled else 0),
    )


async def create_code(user_id: int) -> str:
    """Создаёт одноразовый код, инвалидируя предыдущие."""
    await db.execute(
        "UPDATE bot_2fa_codes SET used=1 WHERE user_id=%s AND used=0", (user_id,)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = datetime.utcnow() + timedelta(seconds=config.TWOFA_CODE_TTL)
    await db.execute(
        "INSERT INTO bot_2fa_codes (user_id, code, expires_at) VALUES (%s, %s, %s)",
        (user_id, code, expires),
    )
    return code


async def verify_code(user_id: int, code: str) -> bool:
    """Проверяет код. Код одноразовый: помечается использованным при успехе."""
    row = await db.fetchone(
        "SELECT id FROM bot_2fa_codes "
        "WHERE user_id=%s AND code=%s AND used=0 AND expires_at > UTC_TIMESTAMP() "
        "ORDER BY id DESC LIMIT 1",
        (user_id, code.strip()),
    )
    if not row:
        return False
    await db.execute("UPDATE bot_2fa_codes SET used=1 WHERE id=%s", (row["id"],))
    return True

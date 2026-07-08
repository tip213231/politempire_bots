"""Работа с существующей таблицей users (аккуратно, ничего не ломаем).

Схема users: id, telegram_id, username (ник MC), email, password, token,
uuid, is_admin, is_banned, balance, created_at, ban_reason, banned_at,
banned_by, last_login.
"""
import hashlib
import uuid as uuid_lib

import bcrypt

from bot import db


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, stored: str | None) -> bool:
    """Проверяет пароль против bcrypt или sha256-хэша (легаси)."""
    if not stored:
        return False
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(password.encode(), stored.encode())
        except ValueError:
            return False
    # легаси: сравниваем sha256 hex
    return hashlib.sha256(password.encode()).hexdigest() == stored


async def get_by_telegram_id(telegram_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM users WHERE telegram_id=%s", (telegram_id,))


async def get_by_username(username: str) -> dict | None:
    return await db.fetchone("SELECT * FROM users WHERE username=%s", (username,))


async def register(telegram_id: int, username: str, password: str) -> tuple[bool, str]:
    """Регистрация/привязка. Возвращает (успех, сообщение)."""
    existing_tg = await get_by_telegram_id(telegram_id)
    if existing_tg:
        return False, f"Этот Telegram уже привязан к нику {existing_tg['username']}."

    user = await get_by_username(username)
    if user:
        # Аккаунт существует: привязываем Telegram только при верном пароле
        if user.get("telegram_id"):
            return False, "Этот ник уже привязан к другому Telegram-аккаунту."
        if not check_password(password, user.get("password")):
            return False, "Неверный пароль от существующего аккаунта."
        await db.execute(
            "UPDATE users SET telegram_id=%s WHERE id=%s", (telegram_id, user["id"])
        )
        return True, f"Telegram привязан к существующему аккаунту {username}."

    # Новый аккаунт
    await db.execute(
        "INSERT INTO users (telegram_id, username, password, uuid, is_admin, is_banned, balance) "
        "VALUES (%s, %s, %s, %s, 0, 0, 0)",
        (telegram_id, username, hash_password(password), str(uuid_lib.uuid4())),
    )
    return True, f"Аккаунт {username} зарегистрирован."


async def is_bot_admin(telegram_id: int) -> bool:
    row = await db.fetchone(
        "SELECT telegram_id FROM bot_admins WHERE telegram_id=%s", (telegram_id,)
    )
    if row:
        return True
    user = await get_by_telegram_id(telegram_id)
    return bool(user and user.get("is_admin"))


async def ban(username: str, reason: str, admin_telegram_id: int) -> bool:
    user = await get_by_username(username)
    if not user:
        return False
    await db.execute(
        "UPDATE users SET is_banned=1, ban_reason=%s, banned_at=NOW(), banned_by=%s WHERE id=%s",
        (reason, admin_telegram_id, user["id"]),
    )
    return True


async def unban(username: str) -> bool:
    user = await get_by_username(username)
    if not user:
        return False
    await db.execute(
        "UPDATE users SET is_banned=0, ban_reason=NULL, banned_at=NULL, banned_by=NULL WHERE id=%s",
        (user["id"],),
    )
    return True


async def delete_account(username: str) -> bool:
    user = await get_by_username(username)
    if not user:
        return False
    await db.execute("DELETE FROM users WHERE id=%s", (user["id"],))
    return True


async def all_telegram_ids() -> list[int]:
    rows = await db.fetchall(
        "SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL AND is_banned=0"
    )
    return [r["telegram_id"] for r in rows]


async def log_admin_action(admin_telegram_id: int, action: str,
                           target: str | None = None, details: str | None = None) -> None:
    await db.execute(
        "INSERT INTO bot_admin_log (admin_telegram_id, action, target, details) "
        "VALUES (%s, %s, %s, %s)",
        (admin_telegram_id, action, target, details),
    )

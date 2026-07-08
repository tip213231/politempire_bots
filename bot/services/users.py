"""Работа с существующей таблицей users (аккуратно, ничего не ломаем).

Схема users: id, telegram_id, username (ник MC), email, password, token,
uuid, is_admin, is_banned, balance, created_at, ban_reason, banned_at,
banned_by, last_login.
"""
import hashlib
import logging
import secrets
import uuid as uuid_lib

import bcrypt

from bot import config, db

log = logging.getLogger(__name__)


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

    # Новый аккаунт. Заполняем ВСЕ текстовые колонки (email/token могут быть
    # NOT NULL без DEFAULT в существующей таблице сайта — иначе INSERT падает).
    try:
        await db.execute(
            "INSERT INTO users (telegram_id, username, email, password, token, uuid, "
            "is_admin, is_banned, balance, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 0, NOW())",
            (
                telegram_id,
                username,
                f"{username.lower()}@tg.politempire.org",  # заглушка вместо email
                hash_password(password),
                secrets.token_hex(32),
                str(uuid_lib.uuid4()),
            ),
        )
    except Exception:
        log.exception("Registration INSERT failed for username=%s tg=%s", username, telegram_id)
        return False, (
            "Не удалось создать аккаунт (ошибка базы данных). "
            "Сообщите администратору."
        )
    return True, f"Аккаунт {username} зарегистрирован."


async def get_by_id(user_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM users WHERE id=%s", (user_id,))


async def list_players(offset: int, limit: int) -> list[dict]:
    """Страница игроков для выбора в админ-панели."""
    return await db.fetchall(
        "SELECT id, username, is_banned FROM users "
        "ORDER BY username ASC LIMIT %s OFFSET %s",
        (limit, offset),
    )


async def count_players() -> int:
    row = await db.fetchone("SELECT COUNT(*) AS c FROM users")
    return int(row["c"]) if row else 0


async def set_password(user_id: int, new_password: str) -> None:
    """Обновляет пароль игрока (bcrypt)."""
    await db.execute(
        "UPDATE users SET password=%s WHERE id=%s",
        (hash_password(new_password), user_id),
    )


async def set_username(user_id: int, new_username: str) -> tuple[bool, str]:
    """Меняет ник игрока. Возвращает (успех, сообщение)."""
    existing = await get_by_username(new_username)
    if existing and existing["id"] != user_id:
        return False, "Этот ник уже занят другим игроком."
    await db.execute(
        "UPDATE users SET username=%s WHERE id=%s", (new_username, user_id)
    )
    return True, "Ник изменён."


def is_super_admin(telegram_id: int) -> bool:
    return telegram_id in config.SUPER_ADMIN_IDS


async def is_bot_admin(telegram_id: int) -> bool:
    if is_super_admin(telegram_id):
        return True
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

"""Пул соединений MySQL и создание НОВЫХ таблиц бота.

ВАЖНО: существующие таблицы (users, bot_admins, bot_sessions) не изменяются.
Бот создаёт только свои таблицы с префиксом bot_ через CREATE TABLE IF NOT EXISTS.
"""
import aiomysql

from bot import config

_pool: aiomysql.Pool | None = None


async def init_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            db=config.DB_NAME,
            autocommit=True,
            charset="utf8mb4",
            minsize=1,
            maxsize=10,
        )
        await _migrate()
    return _pool


def pool() -> aiomysql.Pool:
    assert _pool is not None, "DB pool is not initialized"
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


async def fetchone(sql: str, args: tuple = ()) -> dict | None:
    async with pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return await cur.fetchone()


async def fetchall(sql: str, args: tuple = ()) -> list[dict]:
    async with pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()


async def execute(sql: str, args: tuple = ()) -> int:
    """Выполняет запрос, возвращает lastrowid."""
    async with pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, args)
            return cur.lastrowid


_MIGRATIONS = [
    # Настройки бота (например, обязательная 2FA)
    """
    CREATE TABLE IF NOT EXISTS bot_settings (
        `key` VARCHAR(64) PRIMARY KEY,
        `value` VARCHAR(255) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Состояние 2FA по игроку (привязка к users.id)
    """
    CREATE TABLE IF NOT EXISTS bot_2fa (
        user_id INT PRIMARY KEY,
        enabled TINYINT(1) NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Одноразовые коды 2FA
    """
    CREATE TABLE IF NOT EXISTS bot_2fa_codes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        code VARCHAR(8) NOT NULL,
        expires_at DATETIME NOT NULL,
        used TINYINT(1) NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_2fa_user (user_id, used, expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Персональные инвайт-ссылки Discord
    """
    CREATE TABLE IF NOT EXISTS bot_discord_invites (
        invite_code VARCHAR(32) PRIMARY KEY,
        discord_id BIGINT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_inv_discord (discord_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Рефералы: кто кого пригласил и статус выполнения условий
    """
    CREATE TABLE IF NOT EXISTS bot_referrals (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        invited_discord_id BIGINT NOT NULL UNIQUE,
        inviter_discord_id BIGINT NOT NULL,
        invite_code VARCHAR(32) NOT NULL,
        mc_username VARCHAR(80) DEFAULT NULL,
        playtime_seconds INT NOT NULL DEFAULT 0,
        joined_discord_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed TINYINT(1) NOT NULL DEFAULT 0,
        rewarded TINYINT(1) NOT NULL DEFAULT 0,
        completed_at DATETIME DEFAULT NULL,
        INDEX idx_ref_inviter (inviter_discord_id),
        INDEX idx_ref_mc (mc_username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Привязка ника MC к Discord-аккаунту (для рефералки)
    """
    CREATE TABLE IF NOT EXISTS bot_discord_links (
        discord_id BIGINT PRIMARY KEY,
        mc_username VARCHAR(80) NOT NULL,
        linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_link_mc (mc_username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Журнал начислений/списаний DC Coin
    """
    CREATE TABLE IF NOT EXISTS bot_balance_log (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        mc_username VARCHAR(80) NOT NULL,
        amount INT NOT NULL,
        reason VARCHAR(255) NOT NULL,
        actor VARCHAR(80) NOT NULL DEFAULT 'system',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_bal_user (mc_username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Журнал авторизаций (входы на сервер, 2FA успех/неуспех)
    """
    CREATE TABLE IF NOT EXISTS bot_auth_log (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        mc_username VARCHAR(80) NOT NULL,
        event VARCHAR(32) NOT NULL,
        ip VARCHAR(45) DEFAULT NULL,
        success TINYINT(1) NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_auth_user (mc_username),
        INDEX idx_auth_event (event)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Журнал действий администрации
    """
    CREATE TABLE IF NOT EXISTS bot_admin_log (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        admin_telegram_id BIGINT NOT NULL,
        action VARCHAR(64) NOT NULL,
        target VARCHAR(120) DEFAULT NULL,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Журнал вступлений в Discord по инвайтам
    """
    CREATE TABLE IF NOT EXISTS bot_join_log (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        discord_id BIGINT NOT NULL,
        invite_code VARCHAR(32) DEFAULT NULL,
        inviter_discord_id BIGINT DEFAULT NULL,
        counted TINYINT(1) NOT NULL DEFAULT 0,
        note VARCHAR(255) DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # Активные игровые сессии (для учёта 10 минут)
    """
    CREATE TABLE IF NOT EXISTS bot_play_sessions (
        mc_username VARCHAR(80) PRIMARY KEY,
        joined_at DATETIME NOT NULL,
        ip VARCHAR(45) DEFAULT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


async def _migrate() -> None:
    async with _pool.acquire() as conn:  # type: ignore[union-attr]
        async with conn.cursor() as cur:
            for sql in _MIGRATIONS:
                await cur.execute(sql)


# --- Настройки ---

async def get_setting(key: str, default: str = "") -> str:
    row = await fetchone("SELECT `value` FROM bot_settings WHERE `key`=%s", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await execute(
        "INSERT INTO bot_settings (`key`, `value`) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
        (key, value),
    )

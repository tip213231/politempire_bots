"""Конфигурация из переменных окружения (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# --- База данных (существующая, ничего не ломаем) ---
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = _int("DB_PORT", 3306)
DB_NAME = os.getenv("DB_NAME", "polit_empire")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# --- Telegram ---
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")

# --- Discord ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_GUILD_ID = _int("DISCORD_GUILD_ID", 0)
# Канал, в названии которого показывать онлайн (голосовой или текстовый). 0 = выключено.
DISCORD_STATUS_CHANNEL_ID = _int("DISCORD_STATUS_CHANNEL_ID", 0)
# Интервал обновления онлайна в секундах (Discord ограничивает переименование канала ~2 раза в 10 минут)
ONLINE_UPDATE_INTERVAL = _int("ONLINE_UPDATE_INTERVAL", 60)
CHANNEL_RENAME_INTERVAL = _int("CHANNEL_RENAME_INTERVAL", 300)

# --- Minecraft ---
MC_HOST = os.getenv("MC_HOST", "127.0.0.1")
MC_PORT = _int("MC_PORT", 25565)
RCON_HOST = os.getenv("RCON_HOST", MC_HOST)
RCON_PORT = _int("RCON_PORT", 25575)
RCON_PASSWORD = os.getenv("RCON_PASSWORD", "")

# --- HTTP API для плагина ---
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = _int("API_PORT", 8180)
# Секрет, который плагин передаёт в заголовке X-Api-Secret
API_SECRET = os.getenv("API_SECRET", "")

# --- Логика ---
# Сколько секунд игрок должен провести на сервере, чтобы реферал засчитался
REFERRAL_PLAYTIME_SECONDS = _int("REFERRAL_PLAYTIME_SECONDS", 600)
# Время жизни 2FA-кода в секундах
TWOFA_CODE_TTL = _int("TWOFA_CODE_TTL", 300)

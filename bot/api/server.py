"""HTTP API для Minecraft-плагина.

Плагин на сервере вызывает эти эндпоинты (все запросы с заголовком X-Api-Secret):

POST /api/player/join   {"username": "...", "ip": "..."}
    -> {"require_2fa": true|false}  При require_2fa=true код уже отправлен в Telegram,
       плагин должен заблокировать игрока до POST /api/2fa/verify.

POST /api/2fa/verify    {"username": "...", "code": "..."}
    -> {"ok": true|false}

POST /api/player/quit   {"username": "..."}
    -> {"ok": true}  Закрывает сессию и добавляет наигранное время рефералу.

GET  /api/health        -> {"ok": true}

Учёт 10 минут также ведётся фоновым тиком по открытым сессиям, чтобы награда
выдавалась сразу по достижении порога, а не только при выходе игрока.
"""
import asyncio
import logging
from datetime import datetime

from aiohttp import web

from bot import config, db
from bot.services import referrals, twofa, users
from bot.tg import notify

log = logging.getLogger("api")

TICK_SECONDS = 60


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path.startswith("/api/") and request.path != "/api/health":
        if not config.API_SECRET or request.headers.get("X-Api-Secret") != config.API_SECRET:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def handle_player_join(request: web.Request) -> web.Response:
    data = await request.json()
    username = (data.get("username") or "").strip()
    ip = data.get("ip")
    if not username:
        return web.json_response({"error": "username required"}, status=400)

    user = await users.get_by_username(username)

    # Журнал входа
    await db.execute(
        "INSERT INTO bot_auth_log (mc_username, event, ip, success) VALUES (%s, 'join', %s, 1)",
        (username, ip),
    )

    # Открываем игровую сессию (перезапись, если предыдущая не закрыта)
    await db.execute(
        "INSERT INTO bot_play_sessions (mc_username, joined_at, ip) VALUES (%s, UTC_TIMESTAMP(), %s) "
        "ON DUPLICATE KEY UPDATE joined_at=UTC_TIMESTAMP(), ip=VALUES(ip)",
        (username, ip),
    )

    if user and user.get("is_banned"):
        return web.json_response({"require_2fa": False, "banned": True,
                                  "reason": user.get("ban_reason") or ""})

    # 2FA
    require = False
    if user and await twofa.is_enabled_for_user(user["id"]):
        if user.get("telegram_id"):
            code = await twofa.create_code(user["id"])
            sent = await notify.send_2fa_code(
                user["telegram_id"], username, code, config.TWOFA_CODE_TTL
            )
            require = sent
            if not sent:
                log.error("Could not deliver 2FA code to %s", username)
        else:
            log.warning("2FA enabled for %s but no telegram_id", username)

    return web.json_response({"require_2fa": require, "banned": False})


async def handle_2fa_verify(request: web.Request) -> web.Response:
    data = await request.json()
    username = (data.get("username") or "").strip()
    code = (data.get("code") or "").strip()
    user = await users.get_by_username(username)
    if not user:
        return web.json_response({"ok": False})
    ok = await twofa.verify_code(user["id"], code)
    await db.execute(
        "INSERT INTO bot_auth_log (mc_username, event, success) VALUES (%s, '2fa', %s)",
        (username, 1 if ok else 0),
    )
    return web.json_response({"ok": ok})


async def _close_session(username: str) -> None:
    session = await db.fetchone(
        "SELECT joined_at FROM bot_play_sessions WHERE mc_username=%s", (username,)
    )
    if not session:
        return
    seconds = int((datetime.utcnow() - session["joined_at"]).total_seconds())
    await db.execute("DELETE FROM bot_play_sessions WHERE mc_username=%s", (username,))
    if seconds > 0:
        await referrals.add_playtime(username, min(seconds, 24 * 3600))


async def handle_player_quit(request: web.Request) -> web.Response:
    data = await request.json()
    username = (data.get("username") or "").strip()
    if not username:
        return web.json_response({"error": "username required"}, status=400)
    await db.execute(
        "INSERT INTO bot_auth_log (mc_username, event, success) VALUES (%s, 'quit', 1)",
        (username,),
    )
    await _close_session(username)
    return web.json_response({"ok": True})


async def _playtime_ticker() -> None:
    """Каждую минуту добавляет время открытым сессиям, чтобы порог 10 минут
    срабатывал без ожидания выхода игрока."""
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            sessions = await db.fetchall("SELECT mc_username FROM bot_play_sessions")
            for s in sessions:
                # Сдвигаем joined_at вперёд и засчитываем тик — идемпотентно
                await db.execute(
                    "UPDATE bot_play_sessions SET joined_at=UTC_TIMESTAMP() WHERE mc_username=%s",
                    (s["mc_username"],),
                )
                await referrals.add_playtime(s["mc_username"], TICK_SECONDS)
        except Exception:
            log.exception("playtime ticker error")


async def start_api() -> None:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/player/join", handle_player_join)
    app.router.add_post("/api/player/quit", handle_player_quit)
    app.router.add_post("/api/2fa/verify", handle_2fa_verify)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.API_HOST, config.API_PORT)
    await site.start()
    log.info("API listening on %s:%s", config.API_HOST, config.API_PORT)

    asyncio.create_task(_playtime_ticker())

"""Реферальная система: подсчёт наград, проверка условий, защита от накрутки."""
import logging

from bot import config, db, rcon

log = logging.getLogger("referrals")


def reward_for_referral_number(n: int) -> int:
    """Награда за n-го (1-based) успешно приглашённого игрока."""
    if n <= 5:
        return 10
    if n <= 10:
        return 11
    return 12


async def register_join(invited_discord_id: int, invite_code: str | None,
                        inviter_discord_id: int | None) -> bool:
    """Регистрирует вступление в Discord. Возвращает True, если реферал засчитан как ожидающий.

    Защита от накрутки:
    - один Discord-аккаунт может быть приглашён только один раз (UNIQUE invited_discord_id);
    - самоприглашение не засчитывается.
    """
    counted = False
    note = None
    if inviter_discord_id is None or invite_code is None:
        note = "invite not resolved"
    elif inviter_discord_id == invited_discord_id:
        note = "self-invite"
    else:
        existing = await db.fetchone(
            "SELECT id FROM bot_referrals WHERE invited_discord_id=%s",
            (invited_discord_id,),
        )
        if existing:
            note = "already referred before"
        else:
            await db.execute(
                "INSERT INTO bot_referrals (invited_discord_id, inviter_discord_id, invite_code) "
                "VALUES (%s, %s, %s)",
                (invited_discord_id, inviter_discord_id, invite_code),
            )
            counted = True

    await db.execute(
        "INSERT INTO bot_join_log (discord_id, invite_code, inviter_discord_id, counted, note) "
        "VALUES (%s, %s, %s, %s, %s)",
        (invited_discord_id, invite_code, inviter_discord_id, 1 if counted else 0, note),
    )
    return counted


async def attach_mc_username(discord_id: int, mc_username: str) -> None:
    """Привязывает ник MC к записи реферала приглашённого."""
    await db.execute(
        "UPDATE bot_referrals SET mc_username=%s "
        "WHERE invited_discord_id=%s AND mc_username IS NULL AND completed=0",
        (mc_username, discord_id),
    )


async def add_playtime(mc_username: str, seconds: int) -> None:
    """Добавляет наигранное время и, если условия выполнены, выдаёт награду.

    Идемпотентность: completed/rewarded ставятся атомарно через условный UPDATE,
    поэтому повторные заходы не приносят дополнительной награды.
    """
    if seconds <= 0:
        return
    await db.execute(
        "UPDATE bot_referrals SET playtime_seconds = playtime_seconds + %s "
        "WHERE mc_username=%s AND completed=0",
        (seconds, mc_username),
    )
    ref = await db.fetchone(
        "SELECT * FROM bot_referrals WHERE mc_username=%s AND completed=0 "
        "AND playtime_seconds >= %s",
        (mc_username, config.REFERRAL_PLAYTIME_SECONDS),
    )
    if not ref:
        return

    # Атомарно помечаем завершённым — защита от двойного начисления
    async with db.pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE bot_referrals SET completed=1, completed_at=UTC_TIMESTAMP() "
                "WHERE id=%s AND completed=0",
                (ref["id"],),
            )
            if cur.rowcount != 1:
                return  # уже обработано параллельно

    await _reward_inviter(ref)


async def _reward_inviter(ref: dict) -> None:
    inviter_id = ref["inviter_discord_id"]
    # Номер этого успешного реферала у пригласившего
    row = await db.fetchone(
        "SELECT COUNT(*) AS c FROM bot_referrals "
        "WHERE inviter_discord_id=%s AND completed=1",
        (inviter_id,),
    )
    number = row["c"] if row else 1
    amount = reward_for_referral_number(number)

    # Ник пригласившего для выдачи награды через RCON
    link = await db.fetchone(
        "SELECT mc_username FROM bot_discord_links WHERE discord_id=%s", (inviter_id,)
    )
    if not link:
        log.warning("Inviter %s has no linked MC username; reward %s pending", inviter_id, amount)
        await db.execute(
            "INSERT INTO bot_balance_log (mc_username, amount, reason, actor) "
            "VALUES (%s, %s, %s, %s)",
            (f"discord:{inviter_id}", amount, f"referral #{number} (не выдано: нет привязки ника)", "system"),
        )
        return

    try:
        await rcon.give_coins(
            link["mc_username"], amount,
            f"Награда за реферала #{number} ({ref['mc_username']})",
        )
        await db.execute("UPDATE bot_referrals SET rewarded=1 WHERE id=%s", (ref["id"],))
    except Exception:
        log.exception("Failed to give referral reward to %s", link["mc_username"])


async def stats_for_inviter(inviter_discord_id: int) -> dict:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "SUM(completed) AS completed, SUM(rewarded) AS rewarded "
        "FROM bot_referrals WHERE inviter_discord_id=%s",
        (inviter_discord_id,),
    )
    return {
        "total": row["total"] or 0,
        "completed": int(row["completed"] or 0),
        "rewarded": int(row["rewarded"] or 0),
    }

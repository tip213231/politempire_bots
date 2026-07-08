"""Telegram-бот: регистрация, управление 2FA, админ-панель, рассылка."""
import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)

from bot import db
from bot.services import referrals, twofa, users

log = logging.getLogger("tg")
router = Router()


class Registration(StatesGroup):
    username = State()
    password = State()


class AdminBroadcast(StatesGroup):
    waiting_content = State()


def _esc(text: str) -> str:
    return html.escape(str(text))


def _main_kb(twofa_on: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(
            text=("Выключить 2FA" if twofa_on else "Включить 2FA"),
            callback_data="toggle_2fa",
        )],
    ])


# ---------- Регистрация ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user = await users.get_by_telegram_id(message.from_user.id)
    if user:
        enabled = await twofa.is_enabled_for_user(user["id"])
        await message.answer(
            f"С возвращением, <b>{_esc(user['username'])}</b>!",
            reply_markup=_main_kb(enabled),
        )
        return
    await state.set_state(Registration.username)
    await message.answer(
        "Добро пожаловать! Для регистрации введите ваш <b>ник Minecraft</b>:"
    )


@router.message(Registration.username)
async def reg_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    if not (3 <= len(username) <= 16) or not username.replace("_", "").isalnum():
        await message.answer("Некорректный ник. Введите ник Minecraft (3-16 символов, буквы/цифры/_):")
        return
    await state.update_data(username=username)
    await state.set_state(Registration.password)
    await message.answer("Теперь введите <b>пароль</b> (сообщение будет удалено из чата):")


@router.message(Registration.password)
async def reg_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    # Удаляем сообщение с паролем из чата
    try:
        await message.delete()
    except Exception:
        pass
    if len(password) < 6:
        await message.answer("Пароль слишком короткий (минимум 6 символов). Введите ещё раз:")
        return
    data = await state.get_data()
    ok, msg = await users.register(message.from_user.id, data["username"], password)
    await state.clear()
    if ok:
        user = await users.get_by_telegram_id(message.from_user.id)
        enabled = await twofa.is_enabled_for_user(user["id"])
        await message.answer(f"{_esc(msg)}", reply_markup=_main_kb(enabled))
    else:
        await message.answer(f"{_esc(msg)}\n\nОтправьте /start, чтобы попробовать снова.")


# ---------- Профиль и 2FA ----------

@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery) -> None:
    user = await users.get_by_telegram_id(cb.from_user.id)
    if not user:
        await cb.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return
    enabled = await twofa.is_enabled_for_user(user["id"])
    await cb.message.answer(
        f"<b>Профиль</b>\n"
        f"Ник: <code>{_esc(user['username'])}</code>\n"
        f"Баланс: {user['balance']} DC Coin\n"
        f"2FA: {'включена' if enabled else 'выключена'}\n"
        f"Статус: {'забанен' if user['is_banned'] else 'активен'}"
    )
    await cb.answer()


@router.callback_query(F.data == "toggle_2fa")
async def cb_toggle_2fa(cb: CallbackQuery) -> None:
    user = await users.get_by_telegram_id(cb.from_user.id)
    if not user:
        await cb.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return
    force = await db.get_setting("force_2fa", "0")
    if force == "1":
        await cb.answer("2FA обязательна на сервере и не может быть отключена.", show_alert=True)
        return
    row = await db.fetchone("SELECT enabled FROM bot_2fa WHERE user_id=%s", (user["id"],))
    new_state = not bool(row and row["enabled"])
    await twofa.set_enabled(user["id"], new_state)
    await cb.message.edit_reply_markup(reply_markup=_main_kb(new_state))
    await cb.answer(f"2FA {'включена' if new_state else 'выключена'}")


# ---------- Админ-панель ----------

async def _require_admin(message: Message) -> bool:
    if not await users.is_bot_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return False
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not await _require_admin(message):
        return
    await message.answer(
        "<b>Админ-команды</b>\n"
        "/stats — статистика приглашений и регистраций\n"
        "/balance &lt;ник&gt; — баланс игрока\n"
        "/give &lt;ник&gt; &lt;сумма&gt; — начислить DC Coin (RCON)\n"
        "/take &lt;ник&gt; &lt;сумма&gt; — списать DC Coin (RCON)\n"
        "/reset_referrals &lt;discord_id&gt; — сбросить реф. статистику\n"
        "/force2fa on|off — обязательная 2FA\n"
        "/ban &lt;ник&gt; [причина] — забанить\n"
        "/unban &lt;ник&gt; — разбанить\n"
        "/delete &lt;ник&gt; — удалить аккаунт\n"
        "/log_invites — журнал приглашений\n"
        "/log_balance [ник] — журнал начислений\n"
        "/log_auth [ник] — журнал авторизаций\n"
        "/log_admin — журнал действий администрации\n"
        "/broadcast — рассылка всем игрокам"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not await _require_admin(message):
        return
    regs = await db.fetchone("SELECT COUNT(*) AS c FROM users")
    tg_linked = await db.fetchone("SELECT COUNT(*) AS c FROM users WHERE telegram_id IS NOT NULL")
    refs = await db.fetchone(
        "SELECT COUNT(*) AS total, SUM(completed) AS completed, SUM(rewarded) AS rewarded FROM bot_referrals"
    )
    top = await db.fetchall(
        "SELECT inviter_discord_id, COUNT(*) AS c FROM bot_referrals "
        "WHERE completed=1 GROUP BY inviter_discord_id ORDER BY c DESC LIMIT 5"
    )
    top_text = "\n".join(
        f"  {i+1}. <code>{r['inviter_discord_id']}</code> — {r['c']}" for i, r in enumerate(top)
    ) or "  —"
    await message.answer(
        f"<b>Статистика</b>\n"
        f"Регистраций: {regs['c']} (с Telegram: {tg_linked['c']})\n"
        f"Приглашений: {refs['total'] or 0}, выполнено: {int(refs['completed'] or 0)}, "
        f"награждено: {int(refs['rewarded'] or 0)}\n"
        f"Топ пригласивших:\n{top_text}"
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /balance <ник>")
        return
    user = await users.get_by_username(parts[1])
    if not user:
        await message.answer("Игрок не найден.")
        return
    await message.answer(
        f"Баланс <code>{_esc(user['username'])}</code>: {user['balance']} DC Coin"
    )


async def _give_take(message: Message, give: bool) -> None:
    from bot import rcon
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[2].isdigit() or int(parts[2]) <= 0:
        await message.answer(f"Использование: /{'give' if give else 'take'} <ник> <сумма>")
        return
    username, amount = parts[1], int(parts[2])
    action = "give" if give else "take"
    try:
        fn = rcon.give_coins if give else rcon.take_coins
        await fn(username, amount, f"Ручное {'начисление' if give else 'списание'} администратором",
                 actor=f"tg:{message.from_user.id}")
        await users.log_admin_action(message.from_user.id, f"coins_{action}", username, str(amount))
        await message.answer(f"Готово: {action} {amount} DC Coin — {_esc(username)}")
    except Exception as e:
        log.exception("RCON %s failed", action)
        await message.answer(f"Ошибка RCON: {_esc(e)}")


@router.message(Command("give"))
async def cmd_give(message: Message) -> None:
    if await _require_admin(message):
        await _give_take(message, give=True)


@router.message(Command("take"))
async def cmd_take(message: Message) -> None:
    if await _require_admin(message):
        await _give_take(message, give=False)


@router.message(Command("reset_referrals"))
async def cmd_reset_referrals(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /reset_referrals <discord_id>")
        return
    await db.execute("DELETE FROM bot_referrals WHERE inviter_discord_id=%s", (int(parts[1]),))
    await users.log_admin_action(message.from_user.id, "reset_referrals", parts[1])
    await message.answer(f"Реферальная статистика для <code>{parts[1]}</code> сброшена.")


@router.message(Command("force2fa"))
async def cmd_force2fa(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or parts[1] not in ("on", "off"):
        await message.answer("Использование: /force2fa on|off")
        return
    await db.set_setting("force_2fa", "1" if parts[1] == "on" else "0")
    await users.log_admin_action(message.from_user.id, "force_2fa", parts[1])
    await message.answer(f"Обязательная 2FA: {'включена' if parts[1] == 'on' else 'выключена'}")


@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Использование: /ban <ник> [причина]")
        return
    reason = parts[2] if len(parts) > 2 else "Не указана"
    if await users.ban(parts[1], reason, message.from_user.id):
        await users.log_admin_action(message.from_user.id, "ban", parts[1], reason)
        await message.answer(f"Игрок <code>{_esc(parts[1])}</code> забанен.")
    else:
        await message.answer("Игрок не найден.")


@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /unban <ник>")
        return
    if await users.unban(parts[1]):
        await users.log_admin_action(message.from_user.id, "unban", parts[1])
        await message.answer(f"Игрок <code>{_esc(parts[1])}</code> разбанен.")
    else:
        await message.answer("Игрок не найден.")


@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /delete <ник>")
        return
    if await users.delete_account(parts[1]):
        await users.log_admin_action(message.from_user.id, "delete_account", parts[1])
        await message.answer(f"Аккаунт <code>{_esc(parts[1])}</code> удалён.")
    else:
        await message.answer("Игрок не найден.")


# ---------- Журналы ----------

async def _send_log(message: Message, rows: list[dict], fmt) -> None:
    if not rows:
        await message.answer("Записей нет.")
        return
    text = "\n".join(fmt(r) for r in rows)
    await message.answer(text[:4000])


@router.message(Command("log_invites"))
async def cmd_log_invites(message: Message) -> None:
    if not await _require_admin(message):
        return
    rows = await db.fetchall(
        "SELECT * FROM bot_join_log ORDER BY id DESC LIMIT 20"
    )
    await _send_log(message, rows, lambda r: (
        f"{r['created_at']} | {r['discord_id']} по {r['invite_code'] or '?'} "
        f"от {r['inviter_discord_id'] or '?'} | {'засчитано' if r['counted'] else (r['note'] or 'нет')}"
    ))


@router.message(Command("log_balance"))
async def cmd_log_balance(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) == 2:
        rows = await db.fetchall(
            "SELECT * FROM bot_balance_log WHERE mc_username=%s ORDER BY id DESC LIMIT 20",
            (parts[1],),
        )
    else:
        rows = await db.fetchall("SELECT * FROM bot_balance_log ORDER BY id DESC LIMIT 20")
    await _send_log(message, rows, lambda r: (
        f"{r['created_at']} | {r['mc_username']} {'+' if r['amount'] > 0 else ''}{r['amount']} "
        f"| {r['reason']} | {r['actor']}"
    ))


@router.message(Command("log_auth"))
async def cmd_log_auth(message: Message) -> None:
    if not await _require_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) == 2:
        rows = await db.fetchall(
            "SELECT * FROM bot_auth_log WHERE mc_username=%s ORDER BY id DESC LIMIT 20",
            (parts[1],),
        )
    else:
        rows = await db.fetchall("SELECT * FROM bot_auth_log ORDER BY id DESC LIMIT 20")
    await _send_log(message, rows, lambda r: (
        f"{r['created_at']} | {r['mc_username']} | {r['event']} "
        f"| {'OK' if r['success'] else 'FAIL'} | {r['ip'] or ''}"
    ))


@router.message(Command("log_admin"))
async def cmd_log_admin(message: Message) -> None:
    if not await _require_admin(message):
        return
    rows = await db.fetchall("SELECT * FROM bot_admin_log ORDER BY id DESC LIMIT 20")
    await _send_log(message, rows, lambda r: (
        f"{r['created_at']} | admin {r['admin_telegram_id']} | {r['action']} "
        f"| {r['target'] or ''} | {r['details'] or ''}"
    ))


# ---------- Рассылка ----------

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return
    await state.set_state(AdminBroadcast.waiting_content)
    await message.answer(
        "Отправьте сообщение для рассылки (текст, фото, гифка, файл или опрос). "
        "Для отмены — /cancel"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(AdminBroadcast.waiting_content)
async def broadcast_content(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    ids = await users.all_telegram_ids()
    sent, failed = 0, 0
    for tid in ids:
        try:
            if message.poll:
                # Опросы нельзя копировать — пересылаем
                await bot.forward_message(tid, message.chat.id, message.message_id)
            else:
                await bot.copy_message(tid, message.chat.id, message.message_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # лимиты Telegram ~30 msg/sec
    await users.log_admin_action(
        message.from_user.id, "broadcast", None, f"sent={sent} failed={failed}"
    )
    await message.answer(f"Рассылка завершена. Доставлено: {sent}, ошибок: {failed}.")


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp

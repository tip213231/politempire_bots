"""Telegram-бот: регистрация, управление 2FA, смена пароля, соцсети,
инлайн админ-панель и рассылка."""
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

from bot import config, db
from bot.services import referrals, twofa, users

log = logging.getLogger("tg")
router = Router()


class Registration(StatesGroup):
    username = State()
    password = State()


class ChangePassword(StatesGroup):
    current = State()
    new = State()


class Disable2FA(StatesGroup):
    password = State()


class AdminBroadcast(StatesGroup):
    waiting_content = State()


class AdminAction(StatesGroup):
    """Пошаговый ввод для управления игроком через кнопки.
    Тип действия хранится в data['action']."""
    waiting_nick = State()
    waiting_amount = State()
    waiting_reason = State()


def _esc(text: str) -> str:
    return html.escape(str(text))


# ---------- Клавиатуры ----------

def _main_kb(twofa_on: bool, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(
            text=("🔓 Выключить 2FA" if twofa_on else "🔐 Включить 2FA"),
            callback_data="toggle_2fa",
        )],
        [InlineKeyboardButton(text="🔑 Сменить пароль", callback_data="change_pw")],
        [InlineKeyboardButton(text="🌐 Наши соцсети", callback_data="socials")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])


def _socials_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Discord", url=config.SOCIAL_DISCORD)],
        [InlineKeyboardButton(text="📢 Telegram", url=config.SOCIAL_TELEGRAM)],
        [InlineKeyboardButton(text="🗺 Карта сервера", url=config.SOCIAL_MAP)],
        [InlineKeyboardButton(text="🌍 Сайт", url=config.SOCIAL_SITE)],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])


def _admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="a_stats")],
        [InlineKeyboardButton(text="🧑‍💼 Управление игроком", callback_data="a_players")],
        [
            InlineKeyboardButton(text="📨 Приглашения", callback_data="a_log_invites"),
            InlineKeyboardButton(text="💰 Начисления", callback_data="a_log_balance"),
        ],
        [
            InlineKeyboardButton(text="🔑 Авторизации", callback_data="a_log_auth"),
            InlineKeyboardButton(text="🧾 Действия админов", callback_data="a_log_admin"),
        ],
        [InlineKeyboardButton(text="🔐 Обязательная 2FA вкл/выкл", callback_data="a_force2fa")],
        [InlineKeyboardButton(text="📣 Рассылка", callback_data="a_broadcast")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])


def _admin_players_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс игрока", callback_data="pa_balance")],
        [
            InlineKeyboardButton(text="➕ Начислить DC Coin", callback_data="pa_give"),
            InlineKeyboardButton(text="➖ Списать DC Coin", callback_data="pa_take"),
        ],
        [
            InlineKeyboardButton(text="⛔ Забанить", callback_data="pa_ban"),
            InlineKeyboardButton(text="🟢 Разбанить", callback_data="pa_unban"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="pa_delete"),
            InlineKeyboardButton(text="♻️ Сброс рефералов", callback_data="pa_reset_ref"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")],
    ])


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖️ Отмена", callback_data="a_players")],
    ])


async def _menu_text(user: dict) -> str:
    return (
        f"🏰 <b>PolitEmpire</b>\n\n"
        f"С возвращением, <b>{_esc(user['username'])}</b>! 👋\n"
        f"Выбери действие в меню ниже 👇"
    )


# ---------- Регистрация ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await users.get_by_telegram_id(message.from_user.id)
    if user:
        enabled = await twofa.is_enabled_for_user(user["id"])
        is_admin = await users.is_bot_admin(message.from_user.id)
        await message.answer(await _menu_text(user), reply_markup=_main_kb(enabled, is_admin))
        return
    await state.set_state(Registration.username)
    await message.answer(
        "🏰 <b>Добро пожаловать в PolitEmpire!</b>\n\n"
        "Для регистрации введи свой <b>ник Minecraft</b> 🎮:"
    )


@router.message(Registration.username)
async def reg_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    if not (3 <= len(username) <= 16) or not username.replace("_", "").isalnum():
        await message.answer("⚠️ Некорректный ник. Введи ник Minecraft (3-16 символов, буквы/цифры/_):")
        return
    await state.update_data(username=username)
    await state.set_state(Registration.password)
    await message.answer("🔒 Теперь введи <b>пароль</b> (сообщение будет удалено из чата):")


@router.message(Registration.password)
async def reg_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    if len(password) < 6:
        await message.answer("⚠️ Пароль слишком короткий (минимум 6 символов). Введи ещё раз:")
        return
    data = await state.get_data()
    ok, msg = await users.register(message.from_user.id, data["username"], password)
    await state.clear()
    if ok:
        user = await users.get_by_telegram_id(message.from_user.id)
        enabled = await twofa.is_enabled_for_user(user["id"])
        is_admin = await users.is_bot_admin(message.from_user.id)
        await message.answer(f"✅ {_esc(msg)}", reply_markup=_main_kb(enabled, is_admin))
    else:
        await message.answer(f"❌ {_esc(msg)}\n\nОтправь /start, чтобы попробовать снова.")


# ---------- Меню ----------

@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await users.get_by_telegram_id(cb.from_user.id)
    if not user:
        await cb.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return
    enabled = await twofa.is_enabled_for_user(user["id"])
    is_admin = await users.is_bot_admin(cb.from_user.id)
    try:
        await cb.message.edit_text(await _menu_text(user), reply_markup=_main_kb(enabled, is_admin))
    except Exception:
        await cb.message.answer(await _menu_text(user), reply_markup=_main_kb(enabled, is_admin))
    await cb.answer()


# ---------- Профиль и 2FA ----------

@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery) -> None:
    user = await users.get_by_telegram_id(cb.from_user.id)
    if not user:
        await cb.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return
    enabled = await twofa.is_enabled_for_user(user["id"])
    role = "👑 Администратор" if await users.is_bot_admin(cb.from_user.id) else "🧑 Игрок"
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🎮 Ник: <code>{_esc(user['username'])}</code>\n"
        f"💰 Баланс: <b>{user['balance']}</b> DC Coin\n"
        f"🔐 2FA: {'✅ включена' if enabled else '❌ выключена'}\n"
        f"🚦 Статус: {'⛔ забанен' if user['is_banned'] else '🟢 активен'}\n"
        f"🏅 Роль: {role}"
    )
    try:
        await cb.message.edit_text(text, reply_markup=_back_kb())
    except Exception:
        await cb.message.answer(text, reply_markup=_back_kb())
    await cb.answer()


@router.callback_query(F.data == "toggle_2fa")
async def cb_toggle_2fa(cb: CallbackQuery, state: FSMContext) -> None:
    user = await users.get_by_telegram_id(cb.from_user.id)
    if not user:
        await cb.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return
    force = await db.get_setting("force_2fa", "0")
    if force == "1":
        await cb.answer("🔒 2FA обязательна на сервере и не может быть отключена.", show_alert=True)
        return
    row = await db.fetchone("SELECT enabled FROM bot_2fa WHERE user_id=%s", (user["id"],))
    currently_on = bool(row and row["enabled"])
    if currently_on:
        # Для отключения 2FA требуем текущий пароль
        await state.set_state(Disable2FA.password)
        await cb.message.answer(
            "🔒 Для отключения 2FA введи свой <b>текущий пароль</b>.\n"
            "Сообщение будет удалено. Для отмены — /cancel"
        )
        await cb.answer()
        return
    # Включение — без пароля
    await twofa.set_enabled(user["id"], True)
    is_admin = await users.is_bot_admin(cb.from_user.id)
    try:
        await cb.message.edit_reply_markup(reply_markup=_main_kb(True, is_admin))
    except Exception:
        pass
    await cb.answer("🔐 2FA включена")


@router.message(Disable2FA.password)
async def disable_2fa_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    user = await users.get_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Вы не зарегистрированы. Отправьте /start")
        return
    if not users.check_password(password, user.get("password")):
        await message.answer("❌ Неверный пароль. Попробуй ещё раз или /cancel:")
        return
    await state.clear()
    await twofa.set_enabled(user["id"], False)
    is_admin = await users.is_bot_admin(message.from_user.id)
    await message.answer(
        "🔓 2FA отключена.",
        reply_markup=_main_kb(False, is_admin),
    )


# ---------- Смена пароля ----------

@router.callback_query(F.data == "change_pw")
async def cb_change_pw(cb: CallbackQuery, state: FSMContext) -> None:
    user = await users.get_by_telegram_id(cb.from_user.id)
    if not user:
        await cb.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return
    await state.set_state(ChangePassword.current)
    await cb.message.answer(
        "🔑 <b>Смена пароля</b>\n\n"
        "Введи свой <b>текущий пароль</b> (сообщение будет удалено). Для отмены — /cancel"
    )
    await cb.answer()


@router.message(ChangePassword.current)
async def change_pw_current(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    user = await users.get_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Вы не зарегистрированы. Отправьте /start")
        return
    if not users.check_password(password, user.get("password")):
        await message.answer("❌ Неверный текущий пароль. Попробуй ещё раз или /cancel:")
        return
    await state.set_state(ChangePassword.new)
    await message.answer("✅ Верно! Теперь введи <b>новый пароль</b> (минимум 6 символов):")


@router.message(ChangePassword.new)
async def change_pw_new(message: Message, state: FSMContext) -> None:
    new_password = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    if len(new_password) < 6:
        await message.answer("⚠️ Пароль слишком короткий (минимум 6 символов). Введи ещё раз:")
        return
    user = await users.get_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Вы не зарегистрированы. Отправьте /start")
        return
    await users.set_password(user["id"], new_password)
    await state.clear()
    enabled = await twofa.is_enabled_for_user(user["id"])
    is_admin = await users.is_bot_admin(message.from_user.id)
    await message.answer(
        "✅ Пароль успешно изменён! 🔑",
        reply_markup=_main_kb(enabled, is_admin),
    )


# ---------- Соцсети ----------

@router.callback_query(F.data == "socials")
async def cb_socials(cb: CallbackQuery) -> None:
    text = (
        "🌐 <b>Наши ресурсы</b>\n\n"
        f"💬 Discord: {config.SOCIAL_DISCORD}\n"
        f"📢 Telegram: {config.SOCIAL_TELEGRAM}\n"
        f"🗺 Карта сервера: {config.SOCIAL_MAP}\n"
        f"🌍 Сайт: {config.SOCIAL_SITE}\n\n"
        "Присоединяйся к нашему сообществу! 🎉"
    )
    try:
        await cb.message.edit_text(text, reply_markup=_socials_kb(), disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(text, reply_markup=_socials_kb(), disable_web_page_preview=True)
    await cb.answer()


@router.message(Command("socials"))
async def cmd_socials(message: Message) -> None:
    await message.answer(
        "🌐 <b>Наши ресурсы</b>\n\n"
        "Выбирай куда заглянуть 👇",
        reply_markup=_socials_kb(),
    )


# ---------- Инлайн админ-панель ----------

async def _require_admin(message: Message) -> bool:
    if not await users.is_bot_admin(message.from_user.id):
        await message.answer("🚫 Недостаточно прав.")
        return False
    return True


async def _require_admin_cb(cb: CallbackQuery) -> bool:
    if not await users.is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Недостаточно прав.", show_alert=True)
        return False
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not await _require_admin(message):
        return
    await message.answer(
        "🛠 <b>Админ-п��нель PolitEmpire</b>\n\nВыбери действие 👇",
        reply_markup=_admin_kb(),
    )


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    try:
        await cb.message.edit_text(
            "🛠 <b>Админ-панель PolitEmpire</b>\n\nВыбери действие 👇",
            reply_markup=_admin_kb(),
        )
    except Exception:
        await cb.message.answer(
            "🛠 <b>Админ-панель PolitEmpire</b>\n\nВыбери действие 👇",
            reply_markup=_admin_kb(),
        )
    await cb.answer()


async def _stats_text() -> str:
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
    return (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Регистраций: {regs['c']} (с Telegram: {tg_linked['c']})\n"
        f"📨 Приглашений: {refs['total'] or 0}, выполнено: {int(refs['completed'] or 0)}, "
        f"награждено: {int(refs['rewarded'] or 0)}\n\n"
        f"🏆 Топ пригласивших:\n{top_text}"
    )


@router.callback_query(F.data == "a_stats")
async def cb_a_stats(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    try:
        await cb.message.edit_text(await _stats_text(), reply_markup=_admin_kb())
    except Exception:
        await cb.message.answer(await _stats_text(), reply_markup=_admin_kb())
    await cb.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not await _require_admin(message):
        return
    await message.answer(await _stats_text())


@router.callback_query(F.data == "a_force2fa")
async def cb_a_force2fa(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    current = await db.get_setting("force_2fa", "0")
    new = "0" if current == "1" else "1"
    await db.set_setting("force_2fa", new)
    await users.log_admin_action(cb.from_user.id, "force_2fa", "on" if new == "1" else "off")
    await cb.answer(f"Обязательная 2FA {'включена 🔐' if new == '1' else 'выключена 🔓'}", show_alert=True)


@router.callback_query(F.data == "a_broadcast")
async def cb_a_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin_cb(cb):
        return
    await state.set_state(AdminBroadcast.waiting_content)
    await cb.message.answer(
        "📣 Отправь сообщение для рассылки (текст, фото, гифка, файл или опрос).\n"
        "Для отмены — /cancel"
    )
    await cb.answer()


# ---------- Кнопочное управление игроком ----------

# Что просить у админа для каждого действия и как его подписать.
_PLAYER_ACTIONS = {
    "balance": {"title": "💰 Баланс игрока", "needs": ()},
    "give": {"title": "➕ Начислить DC Coin", "needs": ("amount",)},
    "take": {"title": "➖ Списать DC Coin", "needs": ("amount",)},
    "ban": {"title": "⛔ Забанить игрока", "needs": ("reason",)},
    "unban": {"title": "🟢 Разбанить игрока", "needs": ()},
    "delete": {"title": "🗑 Удалить аккаунт", "needs": ()},
    "reset_ref": {"title": "♻️ Сброс рефералов", "needs": ()},
}


@router.callback_query(F.data == "a_players")
async def cb_a_players(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin_cb(cb):
        return
    await state.clear()
    text = (
        "🧑‍💼 <b>Управление игроком</b>\n\n"
        "Выбери действие — бот пошагово спросит нужные данные 👇"
    )
    try:
        await cb.message.edit_text(text, reply_markup=_admin_players_kb())
    except Exception:
        await cb.message.answer(text, reply_markup=_admin_players_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("pa_"))
async def cb_player_action(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin_cb(cb):
        return
    action = cb.data[len("pa_"):]
    meta = _PLAYER_ACTIONS.get(action)
    if not meta:
        await cb.answer("Неизвестное действие", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminAction.waiting_nick)
    await state.update_data(action=action)
    prompt = (
        f"{meta['title']}\n\n"
        f"Введи <b>ник игрока</b> в Minecraft:"
        if action != "reset_ref"
        else f"{meta['title']}\n\nВведи <b>Discord ID</b> пригласившего:"
    )
    await cb.message.answer(prompt, reply_markup=_cancel_kb())
    await cb.answer()


@router.message(AdminAction.waiting_nick)
async def admin_action_nick(message: Message, state: FSMContext) -> None:
    if not await users.is_bot_admin(message.from_user.id):
        await state.clear()
        return
    value = (message.text or "").strip()
    data = await state.get_data()
    action = data.get("action")

    # Сброс рефералов работает по Discord ID, а не по нику.
    if action == "reset_ref":
        if not value.isdigit():
            await message.answer("⚠️ Discord ID должен быть числом. Введи ещё раз или нажми «Отмена»:")
            return
        await db.execute("DELETE FROM bot_referrals WHERE inviter_discord_id=%s", (int(value),))
        await users.log_admin_action(message.from_user.id, "reset_referrals", value)
        await state.clear()
        await message.answer(
            f"✅ Реферальная статистика для <code>{_esc(value)}</code> сброшена.",
            reply_markup=_admin_players_kb(),
        )
        return

    user = await users.get_by_username(value)
    if not user:
        await message.answer("❌ Игрок не найден. Введи ник ещё раз или нажми «Отмена»:")
        return
    await state.update_data(nick=user["username"])

    meta = _PLAYER_ACTIONS[action]
    if "amount" in meta["needs"]:
        await state.set_state(AdminAction.waiting_amount)
        await message.answer(
            f"Игрок <code>{_esc(user['username'])}</code> найден.\n"
            f"Введи <b>сумму</b> DC Coin (целое число больше 0):",
            reply_markup=_cancel_kb(),
        )
        return
    if "reason" in meta["needs"]:
        await state.set_state(AdminAction.waiting_reason)
        await message.answer(
            f"Игрок <code>{_esc(user['username'])}</code> найден.\n"
            f"Введи <b>причину</b> бана (или «-» чтобы не указывать):",
            reply_markup=_cancel_kb(),
        )
        return
    await _finish_player_action(message, state, action, user["username"])


@router.message(AdminAction.waiting_amount)
async def admin_action_amount(message: Message, state: FSMContext) -> None:
    if not await users.is_bot_admin(message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("⚠️ Введи целое число больше 0 или нажми «Отмена»:")
        return
    data = await state.get_data()
    await _finish_player_action(
        message, state, data["action"], data["nick"], amount=int(raw)
    )


@router.message(AdminAction.waiting_reason)
async def admin_action_reason(message: Message, state: FSMContext) -> None:
    if not await users.is_bot_admin(message.from_user.id):
        await state.clear()
        return
    reason = (message.text or "").strip()
    if reason in ("-", ""):
        reason = "Не указана"
    data = await state.get_data()
    await _finish_player_action(
        message, state, data["action"], data["nick"], reason=reason
    )


async def _finish_player_action(
    message: Message,
    state: FSMContext,
    action: str,
    username: str,
    amount: int | None = None,
    reason: str | None = None,
) -> None:
    """Выполняет выбранное действие и показывает результат с меню управления."""
    await state.clear()
    admin_id = message.from_user.id
    kb = _admin_players_kb()

    if action == "balance":
        user = await users.get_by_username(username)
        bal = user["balance"] if user else 0
        await message.answer(
            f"💰 Баланс <code>{_esc(username)}</code>: <b>{bal}</b> DC Coin",
            reply_markup=kb,
        )
        return

    if action in ("give", "take"):
        from bot import rcon
        give = action == "give"
        try:
            fn = rcon.give_coins if give else rcon.take_coins
            await fn(
                username, amount,
                f"Ручное {'начисление' if give else 'списание'} администратором",
                actor=f"tg:{admin_id}",
            )
            await users.log_admin_action(admin_id, f"coins_{action}", username, str(amount))
            await message.answer(
                f"✅ {'Начислено' if give else 'Списано'} <b>{amount}</b> DC Coin — "
                f"<code>{_esc(username)}</code>",
                reply_markup=kb,
            )
        except Exception as e:
            log.exception("RCON %s failed", action)
            await message.answer(f"❌ Ошибка RCON: {_esc(e)}", reply_markup=kb)
        return

    if action == "ban":
        if await users.ban(username, reason, admin_id):
            await users.log_admin_action(admin_id, "ban", username, reason)
            await message.answer(
                f"⛔ Игрок <code>{_esc(username)}</code> забанен.\nПричина: {_esc(reason)}",
                reply_markup=kb,
            )
        else:
            await message.answer("❌ Игрок не найден.", reply_markup=kb)
        return

    if action == "unban":
        if await users.unban(username):
            await users.log_admin_action(admin_id, "unban", username)
            await message.answer(
                f"🟢 Игрок <code>{_esc(username)}</code> разбанен.", reply_markup=kb
            )
        else:
            await message.answer("❌ Игрок не найден.", reply_markup=kb)
        return

    if action == "delete":
        if await users.delete_account(username):
            await users.log_admin_action(admin_id, "delete_account", username)
            await message.answer(
                f"🗑 Аккаунт <code>{_esc(username)}</code> удалён.", reply_markup=kb
            )
        else:
            await message.answer("❌ Игрок не найден.", reply_markup=kb)
        return


# ---------- Админ-команды (текстовые) ----------

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
        await message.answer("❌ Игрок не найден.")
        return
    await message.answer(
        f"💰 Баланс <code>{_esc(user['username'])}</code>: <b>{user['balance']}</b> DC Coin"
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
        await message.answer(f"✅ Готово: {action} {amount} DC Coin — {_esc(username)}")
    except Exception as e:
        log.exception("RCON %s failed", action)
        await message.answer(f"❌ Ошибка RCON: {_esc(e)}")


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
    await message.answer(f"✅ Реферальная статистика для <code>{parts[1]}</code> сброшена.")


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
    await message.answer(f"🔐 Обязательная 2FA: {'включена' if parts[1] == 'on' else 'выключена'}")


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
        await message.answer(f"⛔ Игрок <code>{_esc(parts[1])}</code> забанен.")
    else:
        await message.answer("❌ Игрок не найден.")


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
        await message.answer(f"🟢 Игрок <code>{_esc(parts[1])}</code> разбанен.")
    else:
        await message.answer("❌ Игрок не найден.")


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
        await message.answer(f"🗑 Аккаунт <code>{_esc(parts[1])}</code> удалён.")
    else:
        await message.answer("❌ Игрок не найден.")


# ---------- Журналы ----------

async def _send_log(target, rows: list[dict], fmt, header: str = "") -> None:
    if not rows:
        text = f"{header}\n\nЗаписей нет." if header else "Записей нет."
    else:
        body = "\n".join(fmt(r) for r in rows)
        text = (f"{header}\n\n{body}" if header else body)[:4000]
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=_admin_kb())
        except Exception:
            await target.message.answer(text, reply_markup=_admin_kb())
        await target.answer()
    else:
        await target.answer(text)


_INVITES_SQL = "SELECT * FROM bot_join_log ORDER BY id DESC LIMIT 20"
_INVITES_FMT = lambda r: (
    f"{r['created_at']} | {r['discord_id']} по {r['invite_code'] or '?'} "
    f"от {r['inviter_discord_id'] or '?'} | {'засчитано' if r['counted'] else (r['note'] or 'нет')}"
)
_ADMIN_LOG_SQL = "SELECT * FROM bot_admin_log ORDER BY id DESC LIMIT 20"
_ADMIN_LOG_FMT = lambda r: (
    f"{r['created_at']} | admin {r['admin_telegram_id']} | {r['action']} "
    f"| {r['target'] or ''} | {r['details'] or ''}"
)
_BALANCE_FMT = lambda r: (
    f"{r['created_at']} | {r['mc_username']} {'+' if r['amount'] > 0 else ''}{r['amount']} "
    f"| {r['reason']} | {r['actor']}"
)
_AUTH_FMT = lambda r: (
    f"{r['created_at']} | {r['mc_username']} | {r['event']} "
    f"| {'OK' if r['success'] else 'FAIL'} | {r['ip'] or ''}"
)


@router.callback_query(F.data == "a_log_invites")
async def cb_log_invites(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    rows = await db.fetchall(_INVITES_SQL)
    await _send_log(cb, rows, _INVITES_FMT, "📨 <b>Журнал приглашений</b>")


@router.callback_query(F.data == "a_log_admin")
async def cb_log_admin(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    rows = await db.fetchall(_ADMIN_LOG_SQL)
    await _send_log(cb, rows, _ADMIN_LOG_FMT, "🧾 <b>Действия администрации</b>")


@router.callback_query(F.data == "a_log_balance")
async def cb_log_balance(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    rows = await db.fetchall("SELECT * FROM bot_balance_log ORDER BY id DESC LIMIT 20")
    await _send_log(cb, rows, _BALANCE_FMT, "💰 <b>Журнал начислений</b>")


@router.callback_query(F.data == "a_log_auth")
async def cb_log_auth(cb: CallbackQuery) -> None:
    if not await _require_admin_cb(cb):
        return
    rows = await db.fetchall("SELECT * FROM bot_auth_log ORDER BY id DESC LIMIT 20")
    await _send_log(cb, rows, _AUTH_FMT, "🔑 <b>Журнал авторизаций</b>")


@router.message(Command("log_invites"))
async def cmd_log_invites(message: Message) -> None:
    if not await _require_admin(message):
        return
    rows = await db.fetchall(_INVITES_SQL)
    await _send_log(message, rows, _INVITES_FMT)


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
    await _send_log(message, rows, _BALANCE_FMT)


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
    await _send_log(message, rows, _AUTH_FMT)


@router.message(Command("log_admin"))
async def cmd_log_admin(message: Message) -> None:
    if not await _require_admin(message):
        return
    rows = await db.fetchall(_ADMIN_LOG_SQL)
    await _send_log(message, rows, _ADMIN_LOG_FMT)


# ---------- Рассылка ----------

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return
    await state.set_state(AdminBroadcast.waiting_content)
    await message.answer(
        "📣 Отправь сообщение для рассылки (текст, фото, гифка, файл или опрос). "
        "Для отмены — /cancel"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✖️ Отменено.")


@router.message(AdminBroadcast.waiting_content)
async def broadcast_content(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    ids = await users.all_telegram_ids()
    sent, failed = 0, 0
    for tid in ids:
        try:
            if message.poll:
                await bot.forward_message(tid, message.chat.id, message.message_id)
            else:
                await bot.copy_message(tid, message.chat.id, message.message_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await users.log_admin_action(
        message.from_user.id, "broadcast", None, f"sent={sent} failed={failed}"
    )
    await message.answer(f"✅ Рассылка завершена. Доставлено: {sent}, ошибок: {failed}.")


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp

# PolitEmpire Bots

Бот для Discord и Telegram с интеграцией с Minecraft-сервером: регистрация игроков,
2FA, реферальная система на Discord-инвайтах, награды в DC Coin через RCON и
отображение онлайна сервера в Discord.

## Возможности

- Регистрация в Telegram-боте (ник + пароль, сообщение с паролем удаляется из чата)
- Двухфакторная аутентификация при входе на Minecraft-сервер (код в Telegram)
- Персональные Discord-инвайты и реферальная система (условие: 10 минут на сервере)
- Награды: 10 DC за первых 5, 11 DC за 6-10, 12 DC начиная с 11-го приглашённого
- Выдача наград через RCON: `donate give <ник> <сумма>`
- Защита от накрутки (уникальные Discord-аккаунты, самоприглашения, повторные заходы)
- Админ-панель в Telegram: статистика, начисление/списание, баны, удаление аккаунтов,
  журналы, рассылка с медиа и опросами
- Онлайн сервера в Discord: статус бота, название канала, команда `/online`

## Установка

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполните значения
python -m bot.main
```

Требуется Python 3.11+.

## База данных

Используется существующая БД `polit_empire`. Существующие таблицы (`users`,
`bot_admins`, `bot_sessions`) не изменяются. При первом запуске бот создаёт свои
таблицы через `CREATE TABLE IF NOT EXISTS`:

| Таблица | Назначение |
|---|---|
| `bot_settings` | настройки (обязательная 2FA) |
| `bot_2fa`, `bot_2fa_codes` | состояние 2FA и одноразовые коды |
| `bot_discord_invites` | персональные инвайт-ссылки |
| `bot_referrals` | кто кого пригласил, наиграно, статус награды |
| `bot_discord_links` | привязка ника MC к Discord (для выдачи наград) |
| `bot_balance_log` | журнал начислений/списаний DC Coin |
| `bot_auth_log` | журнал входов и попыток 2FA |
| `bot_admin_log` | журнал действий администрации |
| `bot_join_log` | журнал вступлений в Discord по инвайтам |
| `bot_play_sessions` | открытые игровые сессии (учёт 10 минут) |

Админы бота: таблица `bot_admins` (telegram_id) либо `users.is_admin = 1`.

## HTTP API для Minecraft-плагина

Бот поднимает HTTP API (по умолчанию порт `8180`). Плагин на сервере должен
вызывать его с заголовком `X-Api-Secret: <API_SECRET>`:

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| POST | `/api/player/join` | `{"username", "ip"}` | `{"require_2fa": bool, "banned": bool}` |
| POST | `/api/2fa/verify` | `{"username", "code"}` | `{"ok": bool}` |
| POST | `/api/player/quit` | `{"username"}` | `{"ok": true}` |
| GET | `/api/health` | — | `{"ok": true}` |

Логика 2FA на стороне плагина:
1. При входе игрока плагин вызывает `/api/player/join`.
2. Если `require_2fa=true` — заблокировать игрока (заморозить, скрыть чат) и ждать
   команду `/2fa <код>`.
3. Код проверять через `/api/2fa/verify`. При `ok=true` — разблокировать,
   иначе — кикнуть или дать повторную попытку.
4. Если `banned=true` — кикнуть с указанием причины.

Учёт 10 минут для рефералки ведётся автоматически по событиям join/quit и
фоновому тику каждую минуту — награда выдаётся сразу по достижении порога.

## Discord-команды

- `/invite` — получить персональную пригласительную ссылку
- `/link <ник>` — привязать ник Minecraft (нужно для получения наград)
- `/referrals` — своя реферальная статистика
- `/online` — онлайн Minecraft-сервера

Боту нужны права: Manage Server (чтение инвайтов), Create Invite,
Manage Channels (переименование статус-канала), а также включённый
Server Members Intent в Discord Developer Portal.

## Telegram-команды (админ)

`/admin` — список всех команд: `/stats`, `/balance`, `/give`, `/take`,
`/reset_referrals`, `/force2fa`, `/ban`, `/unban`, `/delete`,
`/log_invites`, `/log_balance`, `/log_auth`, `/log_admin`, `/broadcast`.

## Структура проекта

```
bot/
  main.py          # точка входа: TG + Discord + API
  config.py        # конфигурация из .env
  db.py            # пул MySQL, миграции таблиц бота
  rcon.py          # выдача/списание DC Coin через RCON
  tg/handlers.py   # Telegram: регистрация, 2FA, админка, рассылка
  tg/notify.py     # отправка 2FA-кодов
  ds/bot.py        # Discord: инвайты, рефералка, онлайн
  api/server.py    # HTTP API для MC-плагина
  services/        # бизнес-логика: users, twofa, referrals
```

## Запуск как сервис (systemd)

```ini
[Unit]
Description=PolitEmpire Bots
After=network.target

[Service]
WorkingDirectory=/opt/politempire_bots
ExecStart=/opt/politempire_bots/venv/bin/python -m bot.main
Restart=always
EnvironmentFile=/opt/politempire_bots/.env

[Install]
WantedBy=multi-user.target
```

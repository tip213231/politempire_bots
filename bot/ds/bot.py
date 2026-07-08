"""Discord-бот: персональные инвайты, рефералка, онлайн Minecraft-сервера."""
import logging

import discord
from discord import app_commands
from discord.ext import tasks
from mcstatus import JavaServer

from bot import config, db
from bot.services import referrals

log = logging.getLogger("ds")

intents = discord.Intents.default()
intents.members = True
intents.invites = True


class PolitEmpireBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._invite_uses: dict[str, int] = {}
        self._last_channel_name: str | None = None
        self._rename_cooldown = 0

    async def setup_hook(self) -> None:
        guild = discord.Object(id=config.DISCORD_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.update_online.start()

    async def on_ready(self) -> None:
        log.info("Discord bot ready as %s", self.user)
        await self._cache_invites()

    async def _cache_invites(self) -> None:
        guild = self.get_guild(config.DISCORD_GUILD_ID)
        if not guild:
            return
        try:
            invites = await guild.invites()
            self._invite_uses = {i.code: i.uses or 0 for i in invites}
        except discord.Forbidden:
            log.error("No permission to read invites (need Manage Server)")

    async def on_invite_create(self, invite: discord.Invite) -> None:
        self._invite_uses[invite.code] = invite.uses or 0

    async def on_invite_delete(self, invite: discord.Invite) -> None:
        self._invite_uses.pop(invite.code, None)

    async def on_member_join(self, member: discord.Member) -> None:
        """Определяем, по какому инвайту вступил пользователь, сравнивая счётчики uses."""
        if member.guild.id != config.DISCORD_GUILD_ID or member.bot:
            return
        used_code = None
        try:
            invites = await member.guild.invites()
        except discord.Forbidden:
            invites = []
        current = {i.code: i.uses or 0 for i in invites}
        for code, uses in current.items():
            if uses > self._invite_uses.get(code, 0):
                used_code = code
                break
        self._invite_uses = current

        inviter_discord_id = None
        if used_code:
            row = await db.fetchone(
                "SELECT discord_id FROM bot_discord_invites WHERE invite_code=%s",
                (used_code,),
            )
            if row:
                inviter_discord_id = row["discord_id"]

        counted = await referrals.register_join(member.id, used_code, inviter_discord_id)
        log.info(
            "Member %s joined via %s (inviter=%s, counted=%s)",
            member.id, used_code, inviter_discord_id, counted,
        )

    # ---------- Онлайн Minecraft ----------

    async def _fetch_status(self) -> tuple[bool, int, int]:
        try:
            server = await JavaServer.async_lookup(f"{config.MC_HOST}:{config.MC_PORT}")
            status = await server.async_status()
            return True, status.players.online, status.players.max
        except Exception:
            return False, 0, 0

    @tasks.loop(seconds=config.ONLINE_UPDATE_INTERVAL)
    async def update_online(self) -> None:
        online, players, slots = await self._fetch_status()
        # Статус бота
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"онлайн: {players}/{slots}" if online else "сервер офлайн",
        )
        try:
            await self.change_presence(activity=activity)
        except Exception:
            pass
        # Название канала (не чаще раза в CHANNEL_RENAME_INTERVAL из-за лимитов Discord)
        if config.DISCORD_STATUS_CHANNEL_ID:
            self._rename_cooldown -= config.ONLINE_UPDATE_INTERVAL
            if self._rename_cooldown > 0:
                return
            name = f"🟢 Онлайн: {players}/{slots}" if online else "🔴 Сервер офлайн"
            if name == self._last_channel_name:
                return
            channel = self.get_channel(config.DISCORD_STATUS_CHANNEL_ID)
            if channel:
                try:
                    await channel.edit(name=name)
                    self._last_channel_name = name
                    self._rename_cooldown = config.CHANNEL_RENAME_INTERVAL
                except Exception:
                    log.exception("Failed to rename status channel")

    @update_online.before_loop
    async def before_update_online(self) -> None:
        await self.wait_until_ready()


client = PolitEmpireBot()


@client.tree.command(name="invite", description="Получить персональную пригласительную ссылку")
async def cmd_invite(interaction: discord.Interaction) -> None:
    row = await db.fetchone(
        "SELECT invite_code FROM bot_discord_invites WHERE discord_id=%s",
        (interaction.user.id,),
    )
    if row:
        await interaction.response.send_message(
            f"Ваша ссылка: https://discord.gg/{row['invite_code']}", ephemeral=True
        )
        return
    guild = interaction.guild
    channel = guild.system_channel or next(
        (c for c in guild.text_channels if c.permissions_for(guild.me).create_instant_invite),
        None,
    )
    if channel is None:
        await interaction.response.send_message(
            "Не удалось создать инвайт: нет подходящего канала.", ephemeral=True
        )
        return
    invite = await channel.create_invite(max_age=0, max_uses=0, unique=True,
                                         reason=f"Referral invite for {interaction.user}")
    await db.execute(
        "INSERT INTO bot_discord_invites (invite_code, discord_id) VALUES (%s, %s)",
        (invite.code, interaction.user.id),
    )
    client._invite_uses[invite.code] = 0
    await interaction.response.send_message(
        f"Ваша персональная ссылка: {invite.url}\n"
        f"Приглашение засчитывается, когда приглашённый зайдёт на Minecraft-сервер "
        f"и проведёт там не менее 10 минут.",
        ephemeral=True,
    )


@client.tree.command(name="link", description="Привязать ник Minecraft для получения наград")
@app_commands.describe(nickname="Ваш ник на Minecraft-сервере")
async def cmd_link(interaction: discord.Interaction, nickname: str) -> None:
    nickname = nickname.strip()
    user = await db.fetchone("SELECT id FROM users WHERE username=%s", (nickname,))
    if not user:
        await interaction.response.send_message(
            "Такой ник не зарегистрирован. Сначала зарегистрируйтесь в Telegram-боте.",
            ephemeral=True,
        )
        return
    taken = await db.fetchone(
        "SELECT discord_id FROM bot_discord_links WHERE mc_username=%s", (nickname,)
    )
    if taken and taken["discord_id"] != interaction.user.id:
        await interaction.response.send_message(
            "Этот ник уже привязан к другому Discord-аккаунту.", ephemeral=True
        )
        return
    await db.execute(
        "INSERT INTO bot_discord_links (discord_id, mc_username) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE mc_username=VALUES(mc_username)",
        (interaction.user.id, nickname),
    )
    # Привязываем ник к записи реферала, если этот пользователь был приглашён
    await referrals.attach_mc_username(interaction.user.id, nickname)
    await interaction.response.send_message(
        f"Ник **{nickname}** привязан. Награды за рефералов будут выдаваться на него.",
        ephemeral=True,
    )


@client.tree.command(name="referrals", description="Моя реферальная статистика")
async def cmd_referrals(interaction: discord.Interaction) -> None:
    stats = await referrals.stats_for_inviter(interaction.user.id)
    await interaction.response.send_message(
        f"Приглашено: {stats['total']}\n"
        f"Выполнили условия: {stats['completed']}\n"
        f"Награждено: {stats['rewarded']}",
        ephemeral=True,
    )


@client.tree.command(name="online", description="Онлайн Minecraft-сервера")
async def cmd_online(interaction: discord.Interaction) -> None:
    online, players, slots = await client._fetch_status()
    if online:
        text = f"🟢 Сервер онлайн\nИгроков: {players}/{slots}"
    else:
        text = "🔴 Сервер офлайн"
    await interaction.response.send_message(text)


async def start_discord_bot() -> None:
    await client.start(config.DISCORD_TOKEN)

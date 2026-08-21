import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands, tasks
import json
import os
import io
import re
import asyncio
import asyncpg
import datetime

# ================= CONFIG =================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Token not found! Set DISCORD_TOKEN")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL not found!")

# Optional: your test server ID.
# If set, slash commands sync to it INSTANTLY (for development).
# If not set, sync is global (can take up to an hour to appear everywhere).
GUILD_ID = os.getenv("GUILD_ID")
TEST_GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None

# Default prefix for new servers. Each server can change it with
# !setprefix / /setprefix — then guild_settings_cache is used instead.
PREFIX = "!"

# ================= DATABASE CONNECTION POOL =================
# A single pool for the whole app instead of new connect()/close() calls per
# query — faster and avoids hitting Postgres' connection limit under load.
db_pool: asyncpg.Pool | None = None

async def init_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)

# ================= DATABASE =================
async def init_db():
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                message_id TEXT PRIMARY KEY,
                data JSONB
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                channel_id TEXT,
                creator_id TEXT,
                topic TEXT,
                closed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                claimed_by TEXT
            )
        """)
        # In case an older deploy already created this table without claimed_by
        await conn.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS claimed_by TEXT")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id SERIAL PRIMARY KEY,
                guild_id TEXT,
                user_id TEXT,
                moderator_id TEXT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        await conn.execute("ALTER TABLE warnings ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT PRIMARY KEY,
                prefix TEXT DEFAULT '!',
                ticket_log_channel_id TEXT,
                ticket_use_threads BOOLEAN DEFAULT FALSE,
                ticket_thread_channel_id TEXT
            )
        """)
        # In case an older deploy already created this table with a different schema
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS prefix TEXT DEFAULT '!'")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ticket_log_channel_id TEXT")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ticket_use_threads BOOLEAN DEFAULT FALSE")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ticket_thread_channel_id TEXT")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ticket_staff_role_id TEXT")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS temp_bans (
                guild_id TEXT,
                user_id TEXT,
                unban_at TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
    print("✅ Tables created")

async def save_translation(message_id: str, data: dict):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO news (message_id, data) VALUES ($1, $2) ON CONFLICT (message_id) DO UPDATE SET data = $2",
            message_id, json.dumps(data, ensure_ascii=False)
        )

async def load_all_translations():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT message_id, data FROM news")
    result = {}
    for row in rows:
        try:
            result[row[0]] = json.loads(row[1])
        except Exception:
            pass
    return result

async def save_ticket(ticket_data: dict):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tickets (ticket_id, channel_id, creator_id, topic, closed, claimed_by) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (ticket_id) DO UPDATE SET closed = $5, claimed_by = $6",
            ticket_data["ticket_id"],
            ticket_data["channel_id"],
            ticket_data["creator_id"],
            ticket_data["topic"],
            ticket_data["closed"],
            ticket_data.get("claimed_by")
        )

async def load_tickets():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ticket_id, channel_id, creator_id, topic, closed, created_at, claimed_by FROM tickets"
        )
    result = {}
    for row in rows:
        result[row[0]] = {
            "ticket_id": row[0],
            "channel_id": row[1],
            "creator_id": row[2],
            "topic": row[3],
            "closed": row[4],
            "created_at": row[5],
            "claimed_by": row[6]
        }
    return result

async def add_warning(guild_id: str, user_id: str, moderator_id: str, reason: str, expires_at: datetime.datetime = None):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, expires_at) VALUES ($1, $2, $3, $4, $5)",
            guild_id, user_id, moderator_id, reason, expires_at
        )

async def get_warnings(guild_id: str, user_id: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, moderator_id, reason, created_at, expires_at FROM warnings WHERE guild_id = $1 AND user_id = $2 ORDER BY created_at DESC",
            guild_id, user_id
        )
    return rows

async def clear_warnings(guild_id: str, user_id: str):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM warnings WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

async def load_expired_warnings():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, guild_id, user_id FROM warnings WHERE expires_at IS NOT NULL AND expires_at <= $1",
            datetime.datetime.utcnow()
        )
    return rows

async def delete_warning(warning_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM warnings WHERE id = $1", warning_id)

# ---- Server settings (prefix, ticket logs, thread/channel mode) ----
DEFAULT_GUILD_SETTINGS = {
    "prefix": "!",
    "ticket_log_channel_id": None,
    "ticket_use_threads": False,
    "ticket_thread_channel_id": None,
    "ticket_staff_role_id": None,
}

async def load_all_guild_settings() -> dict:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT guild_id, prefix, ticket_log_channel_id, ticket_use_threads, ticket_thread_channel_id, ticket_staff_role_id FROM guild_settings"
        )
    result = {}
    for row in rows:
        result[row["guild_id"]] = {
            "prefix": row["prefix"] or "!",
            "ticket_log_channel_id": row["ticket_log_channel_id"],
            "ticket_use_threads": bool(row["ticket_use_threads"]),
            "ticket_thread_channel_id": row["ticket_thread_channel_id"],
            "ticket_staff_role_id": row["ticket_staff_role_id"],
        }
    return result

async def upsert_guild_setting(guild_id: str, **fields):
    """Updates one or more server settings (creates the row if it does not exist yet)."""
    if not fields:
        return
    columns = ["guild_id"] + list(fields.keys())
    values = [guild_id] + list(fields.values())
    placeholders = ", ".join(f"${i+1}" for i in range(len(values)))
    update_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in fields.keys())
    query = (
        f"INSERT INTO guild_settings ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (guild_id) DO UPDATE SET {update_clause}"
    )
    async with db_pool.acquire() as conn:
        await conn.execute(query, *values)

# ---- Temporary bans ----
async def add_temp_ban(guild_id: str, user_id: str, unban_at: datetime.datetime):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO temp_bans (guild_id, user_id, unban_at) VALUES ($1, $2, $3) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET unban_at = $3",
            guild_id, user_id, unban_at
        )

async def remove_temp_ban(guild_id: str, user_id: str):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM temp_bans WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

async def load_due_temp_bans():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT guild_id, user_id FROM temp_bans WHERE unban_at <= $1", datetime.datetime.utcnow())
    return rows

# ================= ALL WORLD LANGUAGES =================
FLAGS = {
    "af": "🇿🇦", "am": "🇪🇹", "ar": "🇸🇦", "az": "🇦🇿",
    "bn": "🇧🇩", "zh": "🇨🇳", "zh-tw": "🇹🇼", "zh-hk": "🇭🇰",
    "hi": "🇮🇳", "id": "🇮🇩", "ja": "🇯🇵", "jv": "🇮🇩",
    "kn": "🇮🇳", "ko": "🇰🇷", "ml": "🇮🇳", "mr": "🇮🇳",
    "ms": "🇲🇾", "my": "🇲🇲", "ne": "🇳🇵", "ta": "🇮🇳",
    "te": "🇮🇳", "th": "🇹🇭", "ur": "🇵🇰", "vi": "🇻🇳",
    "bg": "🇧🇬", "cs": "🇨🇿", "da": "🇩🇰", "nl": "🇳🇱",
    "en": "🇬🇧", "en-us": "🇺🇸", "et": "🇪🇪", "fi": "🇫🇮",
    "fr": "🇫🇷", "de": "🇩🇪", "el": "🇬🇷", "he": "🇮🇱",
    "hu": "🇭🇺", "is": "🇮🇸", "it": "🇮🇹", "lv": "🇱🇻",
    "lt": "🇱🇹", "mk": "🇲🇰", "no": "🇳🇴", "pl": "🇵🇱",
    "pt": "🇵🇹", "pt-br": "🇧🇷", "ro": "🇷🇴", "ru": "🇷🇺",
    "sr": "🇷🇸", "sk": "🇸🇰", "sl": "🇸🇮", "es": "🇪🇸",
    "es-mx": "🇲🇽", "sv": "🇸🇪", "tr": "🇹🇷", "uk": "🇺🇦",
    "mi": "🇳🇿", "ay": "🇧🇴", "qu": "🇵🇪"
}

def get_flag(lang_code: str) -> str:
    return FLAGS.get(lang_code, "🌍")

# ================= BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True  # needed for ban/kick audit-log events, safe to enable

data_store = {}
active_tickets = {}
guild_settings_cache = {}  # guild_id (str) -> settings dict, populated in on_ready

def get_settings(guild_id) -> dict:
    return {**DEFAULT_GUILD_SETTINGS, **guild_settings_cache.get(str(guild_id), {})}

async def get_prefix(bot_, message):
    if message.guild is None:
        return commands.when_mentioned_or("!")(bot_, message)
    prefix = get_settings(message.guild.id)["prefix"]
    return commands.when_mentioned_or(prefix)(bot_, message)

bot = commands.Bot(command_prefix=get_prefix, intents=intents)
bot.remove_command("help")

async def log_ticket_event(guild: discord.Guild, embed: discord.Embed, file: discord.File = None):
    """Sends an embed (and an optional transcript file) to the configured ticket log channel."""
    settings = get_settings(guild.id)
    log_channel_id = settings.get("ticket_log_channel_id")
    if not log_channel_id:
        return
    channel = guild.get_channel(int(log_channel_id))
    if channel is None:
        return
    try:
        if file is not None:
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

async def generate_transcript(channel) -> discord.File:
    """Collects the full message history of a ticket channel/thread into a text file before it's deleted."""
    lines = []
    try:
        async for msg in channel.history(limit=None, oldest_first=True):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = msg.content or "[no text content]"
            lines.append(f"[{ts}] {msg.author} ({msg.author.id}): {content}")
            for attachment in msg.attachments:
                lines.append(f"    [attachment] {attachment.url}")
    except discord.HTTPException:
        pass
    text = "\n".join(lines) if lines else "(no messages)"
    buffer = io.BytesIO(text.encode("utf-8"))
    safe_name = getattr(channel, "name", "ticket")
    return discord.File(buffer, filename=f"transcript-{safe_name}.txt")

async def create_ticket_location(guild: discord.Guild, invoker_channel, member: discord.Member, topic: str):
    """Creates a ticket as either a text channel or a private thread, depending on server settings.
    Returns the created channel/thread object (both support .id, .mention, .send(), .delete())."""
    settings = get_settings(guild.id)

    if settings["ticket_use_threads"]:
        parent_id = settings.get("ticket_thread_channel_id")
        parent = guild.get_channel(int(parent_id)) if parent_id else None
        if parent is None:
            parent = invoker_channel
        thread = await parent.create_thread(
            name=f"ticket-{member.name}"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
            reason=f"Ticket for {member} ({topic})"
        )
        try:
            await thread.add_user(member)
        except discord.HTTPException:
            pass
        return thread
    else:
        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category("Tickets")
        channel = await guild.create_text_channel(
            f"ticket-{member.name}",
            category=category,
            topic=f"Ticket from {member.name}: {topic}",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        return channel

def is_ticket_staff(member: discord.Member) -> bool:
    """Whether this member can manage tickets: admins, anyone with Manage Messages,
    or anyone holding the server's configured ticket staff role."""
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
        return True
    settings = get_settings(member.guild.id)
    role_id = settings.get("ticket_staff_role_id")
    if role_id:
        role = member.guild.get_role(int(role_id))
        if role and role in member.roles:
            return True
    return False

# ================= TRANSLATION BUTTONS =================
class TranslateView(ui.View):
    def __init__(self, message_id: str):
        super().__init__(timeout=None)
        self.message_id = str(message_id)
        self._add_buttons()

    def _add_buttons(self):
        if self.message_id not in data_store:
            return
        langs = data_store[self.message_id]
        for lang_code in sorted(langs.keys(), key=lambda x: (x != "en", x)):
            btn = ui.Button(
                label=lang_code.upper(),
                emoji=get_flag(lang_code),
                style=discord.ButtonStyle.secondary,
                custom_id=f"lang_{lang_code}_{self.message_id}"
            )
            btn.callback = self._make_callback(lang_code)
            self.add_item(btn)

    def _make_callback(self, lang_code: str):
        async def callback(interaction: Interaction):
            msg_id = self.message_id
            if msg_id not in data_store:
                await interaction.response.send_message("❌ News not found.", ephemeral=True)
                return
            text = data_store[msg_id].get(lang_code)
            if not text:
                await interaction.response.send_message(f"❌ No text in {lang_code}.", ephemeral=True)
                return
            await interaction.response.send_message(text, ephemeral=True)
        return callback

# ================= TICKET BUTTONS =================
class TicketApplyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_btn = ui.Button(
            label="✅ Apply!",
            style=discord.ButtonStyle.success,
            custom_id="ticket_apply"
        )
        apply_btn.callback = self.apply_callback
        self.add_item(apply_btn)

    async def apply_callback(self, interaction: Interaction):
        for tid, data in active_tickets.items():
            if data.get("creator_id") == str(interaction.user.id) and not data.get("closed", False):
                await interaction.response.send_message("❌ You already have an open ticket!", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = await create_ticket_location(interaction.guild, interaction.channel, interaction.user, "Support")

        ticket_id = str(channel.id)
        active_tickets[ticket_id] = {
            "ticket_id": ticket_id,
            "channel_id": str(channel.id),
            "creator_id": str(interaction.user.id),
            "topic": "Support",
            "closed": False,
            "created_at": datetime.datetime.utcnow()
        }
        await save_ticket(active_tickets[ticket_id])
        bot.add_view(TicketView(ticket_id))  # register in case of a restart

        embed = discord.Embed(
            title="🎫 Ticket Created",
            description=f"**Created by:** {interaction.user.mention}\n**Support will assist you shortly.**",
            color=discord.Color.blue()
        )
        view = TicketView(ticket_id)
        await channel.send(embed=embed, view=view)

        await interaction.followup.send(f"✅ Ticket created! Go to {channel.mention}", ephemeral=True)

        log_embed = discord.Embed(title="🎫 Ticket Opened", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="User", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Location", value=channel.mention, inline=True)
        log_embed.add_field(name="Topic", value="Support", inline=False)
        await log_ticket_event(interaction.guild, log_embed)

class TicketView(ui.View):
    def __init__(self, ticket_id: str, claimed_by: str = None):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.claimed_by = claimed_by

        claim_btn = ui.Button(
            label="Claimed" if claimed_by else "🙋 Claim",
            style=discord.ButtonStyle.grey if claimed_by else discord.ButtonStyle.primary,
            custom_id=f"claim_ticket_{ticket_id}",
            disabled=bool(claimed_by)
        )
        claim_btn.callback = self.claim_callback
        self.add_item(claim_btn)

        close_btn = ui.Button(
            label="🔒 Close Ticket",
            style=discord.ButtonStyle.danger,
            custom_id=f"close_ticket_{ticket_id}"
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def claim_callback(self, interaction: Interaction):
        if self.ticket_id not in active_tickets:
            await interaction.response.send_message("❌ Ticket not found.", ephemeral=True)
            return

        ticket = active_tickets[self.ticket_id]
        if ticket.get("claimed_by"):
            await interaction.response.send_message("❌ Ticket already claimed.", ephemeral=True)
            return

        if interaction.user.id == int(ticket["creator_id"]):
            await interaction.response.send_message("❌ You can't claim your own ticket.", ephemeral=True)
            return

        if not is_ticket_staff(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to claim tickets.", ephemeral=True)
            return

        ticket["claimed_by"] = str(interaction.user.id)
        await save_ticket(ticket)

        new_view = TicketView(self.ticket_id, claimed_by=ticket["claimed_by"])
        await interaction.response.edit_message(view=new_view)
        await interaction.followup.send(f"🙋 **{interaction.user}** claimed this ticket.")

        log_embed = discord.Embed(title="🙋 Ticket Claimed", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Ticket", value=interaction.channel.mention, inline=True)
        log_embed.add_field(name="Claimed by", value=interaction.user.mention, inline=True)
        await log_ticket_event(interaction.guild, log_embed)

    async def close_callback(self, interaction: Interaction):
        if self.ticket_id not in active_tickets:
            await interaction.response.send_message("❌ Ticket not found.", ephemeral=True)
            return

        ticket = active_tickets[self.ticket_id]
        if ticket["closed"]:
            await interaction.response.send_message("❌ Ticket already closed.", ephemeral=True)
            return

        if interaction.user.id != int(ticket["creator_id"]) and not is_ticket_staff(interaction.user):
            await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
            return

        ticket["closed"] = True
        await save_ticket(ticket)
        await interaction.response.send_message("🔒 Ticket closed. Deleting in 5s...")

        channel = interaction.channel
        transcript_file = await generate_transcript(channel) if channel else None

        log_embed = discord.Embed(title="🔒 Ticket Closed", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Creator", value=f"<@{ticket['creator_id']}>", inline=True)
        log_embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
        if ticket.get("claimed_by"):
            log_embed.add_field(name="Claimed by", value=f"<@{ticket['claimed_by']}>", inline=True)
        log_embed.add_field(name="Topic", value=ticket.get("topic", "—"), inline=False)
        created_at = ticket.get("created_at")
        if created_at:
            log_embed.add_field(name="Duration", value=fmt_duration(datetime.datetime.utcnow() - created_at), inline=False)
        await log_ticket_event(interaction.guild, log_embed, file=transcript_file)

        await asyncio.sleep(5)

        if channel:
            await channel.delete()

# ================= PREFIX COMMANDS =================
@bot.command(name="news")
@commands.has_permissions(manage_messages=True)
async def news_prefix(ctx, *, text: str = None):
    if not text:
        await ctx.send("❌ Usage: `!news <text>`")
        return

    msg = await ctx.send(text)
    msg_id = str(msg.id)

    data_store[msg_id] = {"en": text}
    await save_translation(msg_id, data_store[msg_id])
    await msg.edit(view=TranslateView(msg_id))
    await ctx.send("✅ News published!")

@bot.command(name="lang_add")
async def lang_add_prefix(ctx, message_id: str, lang: str, *, text: str):
    if message_id not in data_store:
        await ctx.send("❌ News not found.")
        return

    data_store[message_id][lang] = text
    await save_translation(message_id, data_store[message_id])

    try:
        channel = ctx.channel
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(view=TranslateView(message_id))
    except Exception as e:
        print(f"Update error: {e}")

    await ctx.send(f"✅ Added {get_flag(lang)} `{lang}`")

@bot.command(name="lang_list")
@commands.has_permissions(manage_messages=True)
async def lang_list_prefix(ctx, message_id: str):
    if message_id not in data_store:
        await ctx.send("❌ News not found.")
        return

    langs = data_store[message_id]
    embed = discord.Embed(
        title=f"📚 Translations for {message_id}",
        description="\n".join([f"{get_flag(k)} **{k.upper()}**: {v[:50]}..." for k, v in langs.items()]),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name="say")
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, text: str):
    await ctx.message.delete()
    await ctx.send(text)

@bot.command(name="ticket_setup")
@commands.has_permissions(administrator=True)
async def ticket_setup(ctx):
    embed = discord.Embed(
        title="🎫 Join MyPvE",
        description="**Open a ticket!**\n\n**Requirements:**\nSilver 3k wins\nGold 1k wins\nPlat+ bypass",
        color=discord.Color.blue()
    )
    view = TicketApplyView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()

@bot.command(name="ticket")
async def ticket_prefix(ctx, *, topic: str = "General support"):
    for tid, data in active_tickets.items():
        if data.get("creator_id") == str(ctx.author.id) and not data.get("closed", False):
            await ctx.send(f"❌ You already have an open ticket.")
            return

    channel = await create_ticket_location(ctx.guild, ctx.channel, ctx.author, topic)

    ticket_id = str(channel.id)
    active_tickets[ticket_id] = {
        "ticket_id": ticket_id,
        "channel_id": str(channel.id),
        "creator_id": str(ctx.author.id),
        "topic": topic,
        "closed": False,
        "created_at": datetime.datetime.utcnow()
    }
    await save_ticket(active_tickets[ticket_id])
    bot.add_view(TicketView(ticket_id))

    embed = discord.Embed(
        title="🎫 New Ticket",
        description=f"**Topic:** {topic}\n**Created by:** {ctx.author.mention}",
        color=discord.Color.blue()
    )
    view = TicketView(ticket_id)
    await channel.send(embed=embed, view=view)
    await ctx.send(f"✅ Ticket created! Go to {channel.mention}")

    log_embed = discord.Embed(title="🎫 Ticket Opened", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="User", value=ctx.author.mention, inline=True)
    log_embed.add_field(name="Location", value=channel.mention, inline=True)
    log_embed.add_field(name="Topic", value=topic, inline=False)
    await log_ticket_event(ctx.guild, log_embed)

@bot.command(name="ticket_close")
async def ticket_close_prefix(ctx):
    ticket_id = str(ctx.channel.id)

    if ticket_id not in active_tickets:
        await ctx.send("❌ This is not a ticket channel.")
        return

    ticket = active_tickets[ticket_id]
    if ticket["closed"]:
        await ctx.send("❌ Ticket already closed.")
        return

    if ctx.author.id != int(ticket["creator_id"]) and not is_ticket_staff(ctx.author):
        await ctx.send("❌ You don't have permission.")
        return

    ticket["closed"] = True
    await save_ticket(ticket)
    await ctx.send("🔒 Ticket closed. Deleting in 5s...")

    transcript_file = await generate_transcript(ctx.channel)

    log_embed = discord.Embed(title="🔒 Ticket Closed", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Creator", value=f"<@{ticket['creator_id']}>", inline=True)
    log_embed.add_field(name="Closed by", value=ctx.author.mention, inline=True)
    if ticket.get("claimed_by"):
        log_embed.add_field(name="Claimed by", value=f"<@{ticket['claimed_by']}>", inline=True)
    log_embed.add_field(name="Topic", value=ticket.get("topic", "—"), inline=False)
    created_at = ticket.get("created_at")
    if created_at:
        log_embed.add_field(name="Duration", value=fmt_duration(datetime.datetime.utcnow() - created_at), inline=False)
    await log_ticket_event(ctx.guild, log_embed, file=transcript_file)

    await asyncio.sleep(5)
    await ctx.channel.delete()

@bot.command(name="ping")
async def ping_prefix(ctx):
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")

# ---- manual slash command re-sync (owner-only) ----
# Nothing needs to be configured: the bot already syncs commands globally on
# every startup (see on_ready). This command is just "do it again right now",
# without waiting for a restart. If GUILD_ID is set, it also syncs instantly
# to that server for faster testing.
@bot.command(name="sync")
@commands.is_owner()
async def sync_prefix(ctx):
    synced_global = await bot.tree.sync()
    msg = f"✅ Synced {len(synced_global)} commands globally (may take a few minutes to appear on clients)."

    if TEST_GUILD is not None:
        bot.tree.copy_global_to(guild=TEST_GUILD)
        synced_guild = await bot.tree.sync(guild=TEST_GUILD)
        msg += f"\n✅ Also synced {len(synced_guild)} commands to this guild instantly."

    await ctx.send(msg)

@bot.command(name="help")
async def help_prefix(ctx):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`!news` — Publish news\n`!lang_add` — Add translation\n`!lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`!ticket_setup` — Setup ticket system\n`!ticket` — Create ticket\n`!ticket_close` — Close ticket\n💡 The `🙋 Claim` and `🔒 Close` buttons appear right inside the ticket.", inline=False)
    embed.add_field(
        name="🛡️ Moderation",
        value="`!kick` `!ban` `!unban` `!mute` `!unmute` `!warn` `!warnings` `!clearwarnings` `!clear`\n"
              "💡 `!ban @user 7d spamming` — temporary ban (`m`/`h`/`d`/`w`), no duration = permanent.",
        inline=False
    )
    embed.add_field(
        name="⚙️ Settings (admin)",
        value="`!setprefix` `!setlogchannel` `!setticketchannel` `!setticketrole` `!ticketmode` `!settings`",
        inline=False
    )
    embed.add_field(name="ℹ️ Other", value="`!say` — Make bot say something\n`!ping` — Check latency\n`!sync` — Re-sync slash commands (owner)\n`!help` — This menu", inline=False)
    await ctx.send(embed=embed)

# ================= MODERATION: PREFIX =================
DURATION_RE = re.compile(r"^(\d+)\s*([mhdw])$", re.IGNORECASE)

def parse_duration(duration: str):
    """'30m' / '12h' / '7d' / '2w' -> timedelta, or None if the format is not recognized."""
    if not duration:
        return None
    match = DURATION_RE.match(duration.strip())
    if not match:
        return None
    amount, unit = match.groups()
    amount = int(amount)
    unit = unit.lower()
    return {
        "m": datetime.timedelta(minutes=amount),
        "h": datetime.timedelta(hours=amount),
        "d": datetime.timedelta(days=amount),
        "w": datetime.timedelta(weeks=amount),
    }[unit]

def fmt_duration(td: datetime.timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if not parts: parts.append(f"{s}s")
    return " ".join(parts)

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You can't kick someone with an equal or higher role.")
        return
    try:
        await member.kick(reason=f"{reason} | by {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to kick this member — make sure my role is above theirs.")
        return
    await ctx.send(f"👢 **{member}** was kicked. Reason: {reason}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You can't ban someone with an equal or higher role.")
        return

    # If the first word of the reason looks like a duration (7d, 12h, 30m, 2w) — temp ban.
    duration_str, delta = None, None
    parts = reason.split(maxsplit=1)
    if parts:
        maybe_delta = parse_duration(parts[0])
        if maybe_delta:
            delta = maybe_delta
            duration_str = parts[0]
            reason = parts[1] if len(parts) > 1 else "No reason provided"

    try:
        await member.ban(reason=f"{reason} | by {ctx.author}", delete_message_days=0)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to ban this member — make sure my role is above theirs.")
        return

    if delta:
        unban_at = datetime.datetime.utcnow() + delta
        await add_temp_ban(str(ctx.guild.id), str(member.id), unban_at)
        await ctx.send(f"🔨 **{member}** was banned for **{duration_str}**. Reason: {reason}")
    else:
        await ctx.send(f"🔨 **{member}** was banned permanently. Reason: {reason}")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban_prefix(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await remove_temp_ban(str(ctx.guild.id), str(user_id))
        await ctx.send(f"✅ **{user}** was unbanned.")
    except discord.NotFound:
        await ctx.send("❌ User is not banned or does not exist.")

@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def mute_prefix(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You can't mute someone with an equal or higher role.")
        return

    delta = parse_duration(duration)
    if delta is None:
        await ctx.send("❌ Invalid duration format. Examples: `10m`, `10h`, `10d`, `1w`.")
        return
    if delta > datetime.timedelta(days=28):
        await ctx.send("❌ Discord timeouts can't exceed 28 days.")
        return

    try:
        await member.timeout(delta, reason=f"{reason} | by {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to timeout this member — make sure my role is above theirs and I have the **Timeout Members** permission.")
        return
    except discord.HTTPException as e:
        await ctx.send(f"❌ Failed to mute: {e}")
        return

    await ctx.send(f"🔇 **{member}** muted for {fmt_duration(delta)}. Reason: {reason}")

@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def unmute_prefix(ctx, member: discord.Member):
    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unmute this member — make sure my role is above theirs.")
        return
    await ctx.send(f"🔊 **{member}** was unmuted.")

@bot.command(name="warn")
@commands.has_permissions(moderate_members=True)
async def warn_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    # If the first word of the reason looks like a duration (7d, 12h, 30m, 2w) — the warning expires automatically.
    duration_str, expires_at = None, None
    parts = reason.split(maxsplit=1)
    if parts:
        delta = parse_duration(parts[0])
        if delta:
            duration_str = parts[0]
            expires_at = datetime.datetime.utcnow() + delta
            reason = parts[1] if len(parts) > 1 else "No reason provided"

    await add_warning(str(ctx.guild.id), str(member.id), str(ctx.author.id), reason, expires_at)
    if duration_str:
        await ctx.send(f"⚠️ **{member}** was warned (expires in {duration_str}). Reason: {reason}")
    else:
        await ctx.send(f"⚠️ **{member}** was warned. Reason: {reason}")
    try:
        await member.send(f"⚠️ You were warned in **{ctx.guild.name}**. Reason: {reason}")
    except discord.Forbidden:
        pass

@bot.command(name="warnings")
@commands.has_permissions(moderate_members=True)
async def warnings_prefix(ctx, member: discord.Member = None):
    member = member or ctx.author
    rows = await get_warnings(str(ctx.guild.id), str(member.id))
    if not rows:
        await ctx.send(f"✅ **{member}** has no warnings.")
        return
    embed = discord.Embed(title=f"⚠️ Warnings for {member}", color=discord.Color.orange())
    for r in rows[:15]:
        mod = ctx.guild.get_member(int(r["moderator_id"]))
        value = f"By: {mod.mention if mod else r['moderator_id']}\nReason: {r['reason']}"
        if r["expires_at"]:
            value += f"\nExpires: {r['expires_at'].strftime('%Y-%m-%d %H:%M')} UTC"
        embed.add_field(
            name=f"#{r['id']} — {r['created_at'].strftime('%Y-%m-%d %H:%M')}",
            value=value,
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="clearwarnings")
@commands.has_permissions(administrator=True)
async def clearwarnings_prefix(ctx, member: discord.Member):
    await clear_warnings(str(ctx.guild.id), str(member.id))
    await ctx.send(f"🧹 Cleared all warnings for **{member}**.")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def clear_prefix(ctx, amount: int):
    amount = max(1, min(amount, 200))
    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to also remove the command itself
    msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.")
    await asyncio.sleep(3)
    await msg.delete()

# ================= SERVER SETTINGS: PREFIX =================
@bot.command(name="setprefix")
@commands.has_permissions(administrator=True)
async def setprefix_prefix(ctx, prefix: str):
    if len(prefix) > 5:
        await ctx.send("❌ Prefix is too long (max 5 characters).")
        return
    await upsert_guild_setting(str(ctx.guild.id), prefix=prefix)
    guild_settings_cache.setdefault(str(ctx.guild.id), {}).update({"prefix": prefix})
    await ctx.send(f"✅ Command prefix for this server changed to `{prefix}`")

@bot.command(name="setlogchannel")
@commands.has_permissions(administrator=True)
async def setlogchannel_prefix(ctx, channel: discord.TextChannel = None):
    channel_id = str(channel.id) if channel else None
    await upsert_guild_setting(str(ctx.guild.id), ticket_log_channel_id=channel_id)
    guild_settings_cache.setdefault(str(ctx.guild.id), {}).update({"ticket_log_channel_id": channel_id})
    if channel:
        await ctx.send(f"✅ Ticket logs will now be sent to {channel.mention}")
    else:
        await ctx.send("✅ Ticket logs disabled.")

@bot.command(name="setticketchannel")
@commands.has_permissions(administrator=True)
async def setticketchannel_prefix(ctx, channel: discord.TextChannel = None):
    channel_id = str(channel.id) if channel else None
    await upsert_guild_setting(str(ctx.guild.id), ticket_thread_channel_id=channel_id)
    guild_settings_cache.setdefault(str(ctx.guild.id), {}).update({"ticket_thread_channel_id": channel_id})
    if channel:
        await ctx.send(f"✅ Ticket threads will now be created in {channel.mention} (relevant when in `threads` mode).")
    else:
        await ctx.send("✅ Ticket thread channel reset — the channel the ticket was opened from will be used instead.")

@bot.command(name="ticketmode")
@commands.has_permissions(administrator=True)
async def ticketmode_prefix(ctx, mode: str):
    mode = mode.lower()
    if mode not in ("channels", "threads"):
        await ctx.send("❌ Mode must be `channels` or `threads`. Example: `!ticketmode threads`")
        return
    use_threads = (mode == "threads")
    await upsert_guild_setting(str(ctx.guild.id), ticket_use_threads=use_threads)
    guild_settings_cache.setdefault(str(ctx.guild.id), {}).update({"ticket_use_threads": use_threads})
    await ctx.send(f"✅ Tickets will now be created as **{'private threads' if use_threads else 'separate channels'}**.")

@bot.command(name="setticketrole")
@commands.has_permissions(administrator=True)
async def setticketrole_prefix(ctx, role: discord.Role = None):
    role_id = str(role.id) if role else None
    await upsert_guild_setting(str(ctx.guild.id), ticket_staff_role_id=role_id)
    guild_settings_cache.setdefault(str(ctx.guild.id), {}).update({"ticket_staff_role_id": role_id})
    if role:
        await ctx.send(f"✅ Members with {role.mention} can now claim and close any ticket (in addition to admins / Manage Messages).")
    else:
        await ctx.send("✅ Ticket staff role cleared — only admins / Manage Messages can manage tickets now.")

@bot.command(name="settings")
@commands.has_permissions(administrator=True)
async def settings_prefix(ctx):
    s = get_settings(ctx.guild.id)
    log_ch = ctx.guild.get_channel(int(s["ticket_log_channel_id"])) if s["ticket_log_channel_id"] else None
    thread_ch = ctx.guild.get_channel(int(s["ticket_thread_channel_id"])) if s["ticket_thread_channel_id"] else None
    staff_role = ctx.guild.get_role(int(s["ticket_staff_role_id"])) if s["ticket_staff_role_id"] else None
    embed = discord.Embed(title="⚙️ Server Settings", color=discord.Color.blurple())
    embed.add_field(name="Prefix", value=f"`{s['prefix']}`", inline=True)
    embed.add_field(name="Ticket mode", value="🧵 Threads" if s["ticket_use_threads"] else "📁 Separate channels", inline=True)
    embed.add_field(name="Ticket log channel", value=log_ch.mention if log_ch else "Not set", inline=False)
    embed.add_field(name="Ticket thread channel", value=thread_ch.mention if thread_ch else "Not set (current channel is used)", inline=False)
    embed.add_field(name="Ticket staff role", value=staff_role.mention if staff_role else "Not set (only admins / Manage Messages)", inline=False)
    await ctx.send(embed=embed)

# ================= SLASH COMMANDS =================
@bot.tree.command(name="news", description="Publish a news post")
@app_commands.describe(
    en="English text (primary)",
    ru="Russian translation (optional)",
    es="Spanish translation (optional)",
    fr="French translation (optional)",
    de="German translation (optional)"
)
@app_commands.default_permissions(manage_messages=True)
async def slash_news(
    interaction: Interaction,
    en: str,
    ru: str = None,
    es: str = None,
    fr: str = None,
    de: str = None
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.sleep(0.5)

    msg = await interaction.channel.send(en.replace("\\n", "\n"))
    msg_id = str(msg.id)

    data_store[msg_id] = {"en": en.replace("\\n", "\n")}
    if ru:
        data_store[msg_id]["ru"] = ru.replace("\\n", "\n")
    if es:
        data_store[msg_id]["es"] = es.replace("\\n", "\n")
    if fr:
        data_store[msg_id]["fr"] = fr.replace("\\n", "\n")
    if de:
        data_store[msg_id]["de"] = de.replace("\\n", "\n")

    await save_translation(msg_id, data_store[msg_id])
    await msg.edit(view=TranslateView(msg_id))
    await interaction.followup.send("✅ News published!", ephemeral=True)

@bot.tree.command(name="lang_add", description="Add translation to news")
@app_commands.describe(
    message_id="ID of the news message",
    lang="Language code (ru, es, fr, de, etc.)",
    text="Translation text"
)
@app_commands.default_permissions(manage_messages=True)
async def slash_lang_add(
    interaction: Interaction,
    message_id: str,
    lang: str,
    text: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    if message_id not in data_store:
        await interaction.followup.send("❌ News not found.", ephemeral=True)
        return

    data_store[message_id][lang] = text.replace("\\n", "\n")
    await save_translation(message_id, data_store[message_id])

    try:
        channel = interaction.channel
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(view=TranslateView(message_id))
    except Exception as e:
        print(f"Update error: {e}")

    await interaction.followup.send(f"✅ Added {get_flag(lang)} `{lang}`", ephemeral=True)

@bot.tree.command(name="lang_list", description="Show all translations for news")
@app_commands.describe(message_id="ID of the news message")
@app_commands.default_permissions(manage_messages=True)
async def slash_lang_list(
    interaction: Interaction,
    message_id: str
):
    if message_id not in data_store:
        await interaction.response.send_message("❌ News not found.", ephemeral=True)
        return

    langs = data_store[message_id]
    embed = discord.Embed(
        title=f"📚 Translations for {message_id}",
        description="\n".join([f"{get_flag(k)} **{k.upper()}**: {v[:50]}..." for k, v in langs.items()]),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="say", description="Make the bot say something")
@app_commands.describe(text="Text to say")
@app_commands.default_permissions(manage_messages=True)
async def slash_say(interaction: Interaction, text: str):
    await interaction.response.send_message(text.replace("\\n", "\n"))

@bot.tree.command(name="ticket_setup", description="Setup the ticket system")
@app_commands.default_permissions(administrator=True)
async def slash_ticket_setup(interaction: Interaction):
    embed = discord.Embed(
        title="🎫 Join MyPvE",
        description="**Open a ticket!**\n\n**Requirements:**\nSilver 3k wins\nGold 1k wins\nPlat+ bypass",
        color=discord.Color.blue()
    )
    view = TicketApplyView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="ticket", description="Create a support ticket")
@app_commands.describe(topic="Ticket topic")
async def slash_ticket(interaction: Interaction, topic: str):
    await interaction.response.defer(ephemeral=True, thinking=True)

    for tid, data in active_tickets.items():
        if data.get("creator_id") == str(interaction.user.id) and not data.get("closed", False):
            await interaction.followup.send(f"❌ You already have an open ticket.", ephemeral=True)
            return

    channel = await create_ticket_location(interaction.guild, interaction.channel, interaction.user, topic)

    ticket_id = str(channel.id)
    active_tickets[ticket_id] = {
        "ticket_id": ticket_id,
        "channel_id": str(channel.id),
        "creator_id": str(interaction.user.id),
        "topic": topic,
        "closed": False,
        "created_at": datetime.datetime.utcnow()
    }
    await save_ticket(active_tickets[ticket_id])
    bot.add_view(TicketView(ticket_id))

    embed = discord.Embed(title="🎫 New Ticket", description=f"**Topic:** {topic}\n**Created by:** {interaction.user.mention}", color=discord.Color.blue())
    view = TicketView(ticket_id)
    await channel.send(embed=embed, view=view)
    await interaction.followup.send(f"✅ Ticket created! Go to {channel.mention}", ephemeral=True)

    log_embed = discord.Embed(title="🎫 Ticket Opened", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="User", value=interaction.user.mention, inline=True)
    log_embed.add_field(name="Location", value=channel.mention, inline=True)
    log_embed.add_field(name="Topic", value=topic, inline=False)
    await log_ticket_event(interaction.guild, log_embed)

@bot.tree.command(name="ticket_close", description="Close the current ticket")
async def slash_ticket_close(interaction: Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    ticket_id = str(interaction.channel.id)

    if ticket_id not in active_tickets:
        await interaction.followup.send("❌ This is not a ticket channel.", ephemeral=True)
        return

    ticket = active_tickets[ticket_id]
    if ticket["closed"]:
        await interaction.followup.send("❌ Ticket already closed.", ephemeral=True)
        return

    if interaction.user.id != int(ticket["creator_id"]) and not is_ticket_staff(interaction.user):
        await interaction.followup.send("❌ You don't have permission.", ephemeral=True)
        return

    ticket["closed"] = True
    await save_ticket(ticket)
    await interaction.channel.send("🔒 Ticket closed. Deleting in 5s...")

    transcript_file = await generate_transcript(interaction.channel)

    log_embed = discord.Embed(title="🔒 Ticket Closed", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Creator", value=f"<@{ticket['creator_id']}>", inline=True)
    log_embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
    if ticket.get("claimed_by"):
        log_embed.add_field(name="Claimed by", value=f"<@{ticket['claimed_by']}>", inline=True)
    log_embed.add_field(name="Topic", value=ticket.get("topic", "—"), inline=False)
    created_at = ticket.get("created_at")
    if created_at:
        log_embed.add_field(name="Duration", value=fmt_duration(datetime.datetime.utcnow() - created_at), inline=False)
    await log_ticket_event(interaction.guild, log_embed, file=transcript_file)

    await asyncio.sleep(5)
    await interaction.channel.delete()
    await interaction.followup.send("✅ Ticket closed.", ephemeral=True)

@bot.tree.command(name="ping", description="Check bot latency")
async def slash_ping(interaction: Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms", ephemeral=True)

@bot.tree.command(name="help", description="Show all commands")
async def slash_commands(interaction: Interaction):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`/news` — Publish news\n`/lang_add` — Add translation\n`/lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket_setup` — Setup ticket system\n`/ticket` — Create ticket\n`/ticket_close` — Close ticket\n💡 The `🙋 Claim` and `🔒 Close` buttons appear right inside the ticket.", inline=False)
    embed.add_field(
        name="🛡️ Moderation",
        value="`/kick` `/ban` `/unban` `/mute` `/unmute` `/warn` `/warnings` `/clearwarnings` `/clear`\n"
              "💡 `/ban` — the `duration` parameter (e.g. `7d`, `12h`, `30m`) makes the ban temporary.",
        inline=False
    )
    embed.add_field(
        name="⚙️ Settings (admin)",
        value="`/setprefix` `/setlogchannel` `/setticketchannel` `/setticketrole` `/ticketmode` `/settings`",
        inline=False
    )
    embed.add_field(name="ℹ️ Other", value="`/say` — Make bot say something\n`/ping` — Check latency\n`/help` — This menu", inline=False)
    embed.add_field(name="📝 Prefix commands", value="Use `!` before commands (e.g. `!news`)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= MODERATION: SLASH =================
@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(member="Who to kick", reason="Reason")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You can't kick someone with an equal or higher role.", ephemeral=True)
        return
    try:
        await member.kick(reason=f"{reason} | by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to kick this member — make sure my role is above theirs.", ephemeral=True)
        return
    await interaction.response.send_message(f"👢 **{member}** was kicked. Reason: {reason}", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member, optionally temporary")
@app_commands.describe(member="Who to ban", duration="e.g. 30m, 12h, 7d, 2w — leave empty for a permanent ban", reason="Reason")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: Interaction, member: discord.Member, duration: str = None, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You can't ban someone with an equal or higher role.", ephemeral=True)
        return

    delta = None
    if duration:
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message("❌ Invalid duration format. Examples: `30m`, `12h`, `7d`, `2w`.", ephemeral=True)
            return

    try:
        await member.ban(reason=f"{reason} | by {interaction.user}", delete_message_days=0)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to ban this member — make sure my role is above theirs.", ephemeral=True)
        return

    if delta:
        unban_at = datetime.datetime.utcnow() + delta
        await add_temp_ban(str(interaction.guild.id), str(member.id), unban_at)
        await interaction.response.send_message(f"🔨 **{member}** was banned for **{duration}**. Reason: {reason}", ephemeral=True)
    else:
        await interaction.response.send_message(f"🔨 **{member}** was banned permanently. Reason: {reason}", ephemeral=True)

@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="User ID to unban")
@app_commands.default_permissions(ban_members=True)
async def slash_unban(interaction: Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await remove_temp_ban(str(interaction.guild.id), user_id)
        await interaction.response.send_message(f"✅ **{user}** was unbanned.", ephemeral=True)
    except (discord.NotFound, ValueError):
        await interaction.response.send_message("❌ User is not banned or ID is invalid.", ephemeral=True)

@bot.tree.command(name="mute", description="Timeout a member")
@app_commands.describe(member="Who to mute", duration="e.g. 10m, 10h, 10d, 1w", reason="Reason")
@app_commands.default_permissions(moderate_members=True)
async def slash_mute(interaction: Interaction, member: discord.Member, duration: str, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You can't mute someone with an equal or higher role.", ephemeral=True)
        return

    delta = parse_duration(duration)
    if delta is None:
        await interaction.response.send_message("❌ Invalid duration format. Examples: `10m`, `10h`, `10d`, `1w`.", ephemeral=True)
        return
    if delta > datetime.timedelta(days=28):
        await interaction.response.send_message("❌ Discord timeouts can't exceed 28 days.", ephemeral=True)
        return

    try:
        await member.timeout(delta, reason=f"{reason} | by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to timeout this member — make sure my role is above theirs and I have the **Timeout Members** permission.", ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.response.send_message(f"❌ Failed to mute: {e}", ephemeral=True)
        return

    await interaction.response.send_message(f"🔇 **{member}** muted for {fmt_duration(delta)}. Reason: {reason}", ephemeral=True)

@bot.tree.command(name="unmute", description="Remove a timeout")
@app_commands.describe(member="Who to unmute")
@app_commands.default_permissions(moderate_members=True)
async def slash_unmute(interaction: Interaction, member: discord.Member):
    try:
        await member.timeout(None, reason=f"Unmuted by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unmute this member — make sure my role is above theirs.", ephemeral=True)
        return
    await interaction.response.send_message(f"🔊 **{member}** was unmuted.", ephemeral=True)

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Who to warn", duration="Optional — e.g. 7d, 12h — the warning auto-expires after this", reason="Reason")
@app_commands.default_permissions(moderate_members=True)
async def slash_warn(interaction: Interaction, member: discord.Member, duration: str = None, reason: str = "No reason provided"):
    expires_at = None
    if duration:
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message("❌ Invalid duration format. Examples: `7d`, `12h`, `30m`.", ephemeral=True)
            return
        expires_at = datetime.datetime.utcnow() + delta

    await add_warning(str(interaction.guild.id), str(member.id), str(interaction.user.id), reason, expires_at)
    if duration:
        await interaction.response.send_message(f"⚠️ **{member}** was warned (expires in {duration}). Reason: {reason}", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ **{member}** was warned. Reason: {reason}", ephemeral=True)
    try:
        await member.send(f"⚠️ You were warned in **{interaction.guild.name}**. Reason: {reason}")
    except discord.Forbidden:
        pass

@bot.tree.command(name="warnings", description="Show warnings for a member")
@app_commands.describe(member="Member to check")
@app_commands.default_permissions(moderate_members=True)
async def slash_warnings(interaction: Interaction, member: discord.Member = None):
    member = member or interaction.user
    rows = await get_warnings(str(interaction.guild.id), str(member.id))
    if not rows:
        await interaction.response.send_message(f"✅ **{member}** has no warnings.", ephemeral=True)
        return
    embed = discord.Embed(title=f"⚠️ Warnings for {member}", color=discord.Color.orange())
    for r in rows[:15]:
        mod = interaction.guild.get_member(int(r["moderator_id"]))
        value = f"By: {mod.mention if mod else r['moderator_id']}\nReason: {r['reason']}"
        if r["expires_at"]:
            value += f"\nExpires: {r['expires_at'].strftime('%Y-%m-%d %H:%M')} UTC"
        embed.add_field(
            name=f"#{r['id']} — {r['created_at'].strftime('%Y-%m-%d %H:%M')}",
            value=value,
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member")
@app_commands.describe(member="Member to clear")
@app_commands.default_permissions(administrator=True)
async def slash_clearwarnings(interaction: Interaction, member: discord.Member):
    await clear_warnings(str(interaction.guild.id), str(member.id))
    await interaction.response.send_message(f"🧹 Cleared all warnings for **{member}**.", ephemeral=True)

@bot.tree.command(name="clear", description="Bulk delete messages in this channel")
@app_commands.describe(amount="How many messages to delete (max 200)")
@app_commands.default_permissions(manage_messages=True)
async def slash_clear(interaction: Interaction, amount: app_commands.Range[int, 1, 200]):
    await interaction.response.defer(ephemeral=True, thinking=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

# ================= SERVER SETTINGS: SLASH =================
@bot.tree.command(name="setprefix", description="Change the command prefix for this server")
@app_commands.describe(prefix="New prefix, e.g. ! or ?")
@app_commands.default_permissions(administrator=True)
async def slash_setprefix(interaction: Interaction, prefix: str):
    if len(prefix) > 5:
        await interaction.response.send_message("❌ Prefix is too long (max 5 characters).", ephemeral=True)
        return
    await upsert_guild_setting(str(interaction.guild.id), prefix=prefix)
    guild_settings_cache.setdefault(str(interaction.guild.id), {}).update({"prefix": prefix})
    await interaction.response.send_message(f"✅ Command prefix for this server changed to `{prefix}`", ephemeral=True)

@bot.tree.command(name="setlogchannel", description="Set the channel for ticket logs")
@app_commands.describe(channel="Channel to send ticket logs to (leave empty to disable)")
@app_commands.default_permissions(administrator=True)
async def slash_setlogchannel(interaction: Interaction, channel: discord.TextChannel = None):
    channel_id = str(channel.id) if channel else None
    await upsert_guild_setting(str(interaction.guild.id), ticket_log_channel_id=channel_id)
    guild_settings_cache.setdefault(str(interaction.guild.id), {}).update({"ticket_log_channel_id": channel_id})
    if channel:
        await interaction.response.send_message(f"✅ Ticket logs will now be sent to {channel.mention}", ephemeral=True)
    else:
        await interaction.response.send_message("✅ Ticket logs disabled.", ephemeral=True)

@bot.tree.command(name="setticketchannel", description="Set the parent channel used to create ticket threads")
@app_commands.describe(channel="Channel where ticket threads will be created (leave empty to reset)")
@app_commands.default_permissions(administrator=True)
async def slash_setticketchannel(interaction: Interaction, channel: discord.TextChannel = None):
    channel_id = str(channel.id) if channel else None
    await upsert_guild_setting(str(interaction.guild.id), ticket_thread_channel_id=channel_id)
    guild_settings_cache.setdefault(str(interaction.guild.id), {}).update({"ticket_thread_channel_id": channel_id})
    if channel:
        await interaction.response.send_message(f"✅ Ticket threads will now be created in {channel.mention} (relevant when in `threads` mode).", ephemeral=True)
    else:
        await interaction.response.send_message("✅ Ticket thread channel reset — the channel the ticket was opened from will be used instead.", ephemeral=True)

@bot.tree.command(name="ticketmode", description="Choose whether tickets are channels or threads")
@app_commands.describe(mode="channels or threads")
@app_commands.choices(mode=[
    app_commands.Choice(name="Channels (separate channels)", value="channels"),
    app_commands.Choice(name="Threads (private threads)", value="threads"),
])
@app_commands.default_permissions(administrator=True)
async def slash_ticketmode(interaction: Interaction, mode: app_commands.Choice[str]):
    use_threads = (mode.value == "threads")
    await upsert_guild_setting(str(interaction.guild.id), ticket_use_threads=use_threads)
    guild_settings_cache.setdefault(str(interaction.guild.id), {}).update({"ticket_use_threads": use_threads})
    await interaction.response.send_message(f"✅ Tickets will now be created as **{'private threads' if use_threads else 'separate channels'}**.", ephemeral=True)

@bot.tree.command(name="setticketrole", description="Set the role allowed to claim/close any ticket")
@app_commands.describe(role="Role that can manage tickets (leave empty to reset to admins only)")
@app_commands.default_permissions(administrator=True)
async def slash_setticketrole(interaction: Interaction, role: discord.Role = None):
    role_id = str(role.id) if role else None
    await upsert_guild_setting(str(interaction.guild.id), ticket_staff_role_id=role_id)
    guild_settings_cache.setdefault(str(interaction.guild.id), {}).update({"ticket_staff_role_id": role_id})
    if role:
        await interaction.response.send_message(f"✅ Members with {role.mention} can now claim and close any ticket (in addition to admins / Manage Messages).", ephemeral=True)
    else:
        await interaction.response.send_message("✅ Ticket staff role cleared — only admins / Manage Messages can manage tickets now.", ephemeral=True)

@bot.tree.command(name="settings", description="Show current server settings")
@app_commands.default_permissions(administrator=True)
async def slash_settings(interaction: Interaction):
    s = get_settings(interaction.guild.id)
    log_ch = interaction.guild.get_channel(int(s["ticket_log_channel_id"])) if s["ticket_log_channel_id"] else None
    thread_ch = interaction.guild.get_channel(int(s["ticket_thread_channel_id"])) if s["ticket_thread_channel_id"] else None
    staff_role = interaction.guild.get_role(int(s["ticket_staff_role_id"])) if s["ticket_staff_role_id"] else None
    embed = discord.Embed(title="⚙️ Server Settings", color=discord.Color.blurple())
    embed.add_field(name="Prefix", value=f"`{s['prefix']}`", inline=True)
    embed.add_field(name="Ticket mode", value="🧵 Threads" if s["ticket_use_threads"] else "📁 Separate channels", inline=True)
    embed.add_field(name="Ticket log channel", value=log_ch.mention if log_ch else "Not set", inline=False)
    embed.add_field(name="Ticket thread channel", value=thread_ch.mention if thread_ch else "Not set (current channel is used)", inline=False)
    embed.add_field(name="Ticket staff role", value=staff_role.mention if staff_role else "Not set (only admins / Manage Messages)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= RESTORE =================
async def restore_news_messages():
    for msg_id, data in data_store.items():
        try:
            for guild in bot.guilds:
                for channel in guild.text_channels:
                    try:
                        msg = await channel.fetch_message(int(msg_id))
                        await msg.edit(view=TranslateView(msg_id))
                        print(f"✅ Restored news {msg_id} in {channel.name}")
                        break
                    except Exception:
                        continue
        except Exception as e:
            print(f"❌ Could not restore news {msg_id}: {e}")

async def restore_tickets():
    tickets = await load_tickets()
    for ticket_id, ticket_data in tickets.items():
        if not ticket_data["closed"]:
            active_tickets[ticket_id] = ticket_data
            bot.add_view(TicketView(ticket_id, claimed_by=ticket_data.get("claimed_by")))  # so buttons keep working after a restart
            print(f"✅ Restored ticket {ticket_id}")

# ================= TEMPORARY BANS =================
@tasks.loop(minutes=1)
async def check_temp_bans():
    try:
        due = await load_due_temp_bans()
    except Exception as e:
        print(f"❌ Failed to load due temp bans: {e}")
        return

    for row in due:
        guild_id, user_id = row["guild_id"], row["user_id"]
        guild = bot.get_guild(int(guild_id))
        if guild is None:
            await remove_temp_ban(guild_id, user_id)
            continue
        try:
            user = await bot.fetch_user(int(user_id))
            await guild.unban(user, reason="Temp ban expired")
            print(f"✅ Auto-unbanned {user} in {guild.name}")
        except discord.NotFound:
            pass  # already unbanned manually
        except discord.HTTPException as e:
            print(f"❌ Failed to auto-unban {user_id} in {guild_id}: {e}")
        finally:
            await remove_temp_ban(guild_id, user_id)

@check_temp_bans.before_loop
async def before_check_temp_bans():
    await bot.wait_until_ready()

# ================= TEMPORARY WARNINGS =================
@tasks.loop(minutes=1)
async def check_expired_warnings():
    try:
        expired = await load_expired_warnings()
    except Exception as e:
        print(f"❌ Failed to load expired warnings: {e}")
        return

    for row in expired:
        await delete_warning(row["id"])
        print(f"✅ Expired warning #{row['id']} removed (guild {row['guild_id']}, user {row['user_id']})")

@check_expired_warnings.before_loop
async def before_check_expired_warnings():
    await bot.wait_until_ready()

# ================= EVENTS =================
@bot.event
async def on_ready():
    global data_store, guild_settings_cache

    try:
        if db_pool is None:
            await init_db_pool()
        async with db_pool.acquire() as conn:
            await conn.execute("SELECT 1")
        print("✅ PostgreSQL pool connected!")
    except Exception as e:
        print(f"❌ DB error: {e}")
        return

    await init_db()
    data_store = await load_all_translations()
    guild_settings_cache = await load_all_guild_settings()

    # register a persistent view for the ticket panel's "Apply" button (not tied to a message_id)
    bot.add_view(TicketApplyView())

    await restore_tickets()
    await restore_news_messages()

    if not check_temp_bans.is_running():
        check_temp_bans.start()
    if not check_expired_warnings.is_running():
        check_expired_warnings.start()

    # SYNC SLASH COMMANDS
    try:
        if TEST_GUILD is not None:
            bot.tree.copy_global_to(guild=TEST_GUILD)
            synced = await bot.tree.sync(guild=TEST_GUILD)
            print(f"✅ Slash commands synced to test guild ({len(synced)} commands, instantly visible there)")
        else:
            synced = await bot.tree.sync()
            print(f"✅ Slash commands synced globally ({len(synced)} commands, may take up to 1h to appear everywhere)")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")

    await bot.change_presence(status=discord.Status.online)

    print(f"✅ Bot online as {bot.user}")
    print(f"📰 Loaded: {len(data_store)} news")
    print(f"🎫 Loaded: {len(active_tickets)} active tickets")
    print("❓ Use !help or /help")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("❌ I'm missing permissions to do that (check role position / server settings).")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Member not found.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Bad argument. Check the command usage.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        print(f"Command error: {error}")

# Slash command error handler — without it a failed /command just "doesn't respond"
# in the Discord client, with no explanation for the user.
async def on_app_command_error(interaction: Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        text = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        text = "❌ I'm missing permissions to do that (check my role position / server settings)."
    elif isinstance(error, app_commands.CommandOnCooldown):
        text = f"⏳ This command is on cooldown. Try again in {error.retry_after:.1f}s."
    elif isinstance(error, app_commands.CheckFailure):
        text = "❌ You can't use this command here."
    else:
        print(f"App command error in /{interaction.command.name if interaction.command else '?'}: {error}")
        text = "❌ Something went wrong while running that command."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass

bot.tree.on_error = on_app_command_error

# ================= STARTUP =================
if __name__ == "__main__":
    bot.run(TOKEN)

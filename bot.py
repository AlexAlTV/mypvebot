import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands
import json
import os
import asyncio
import asyncpg
import datetime

# ================= КОНФИГ =================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Token not found! Set DISCORD_TOKEN")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL not found!")

# Необязательно: ID вашего тестового сервера.
# Если указан — слеш-команды синкаются в него МГНОВЕННО (для разработки).
# Если не указан — синк глобальный (может занять до 1 часа на всех серверах).
GUILD_ID = os.getenv("GUILD_ID")
TEST_GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None

PREFIX = "!"

# ================= БАЗА ДАННЫХ =================
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id SERIAL PRIMARY KEY,
            guild_id TEXT,
            user_id TEXT,
            moderator_id TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.close()
    print("✅ Tables created")

async def save_translation(message_id: str, data: dict):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO news (message_id, data) VALUES ($1, $2) ON CONFLICT (message_id) DO UPDATE SET data = $2",
        message_id, json.dumps(data, ensure_ascii=False)
    )
    await conn.close()

async def load_all_translations():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT message_id, data FROM news")
    await conn.close()
    result = {}
    for row in rows:
        try:
            result[row[0]] = json.loads(row[1])
        except Exception:
            pass
    return result

async def save_ticket(ticket_data: dict):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO tickets (ticket_id, channel_id, creator_id, topic, closed) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (ticket_id) DO UPDATE SET closed = $5",
        ticket_data["ticket_id"],
        ticket_data["channel_id"],
        ticket_data["creator_id"],
        ticket_data["topic"],
        ticket_data["closed"]
    )
    await conn.close()

async def load_tickets():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT ticket_id, channel_id, creator_id, topic, closed FROM tickets")
    await conn.close()
    result = {}
    for row in rows:
        result[row[0]] = {
            "ticket_id": row[0],
            "channel_id": row[1],
            "creator_id": row[2],
            "topic": row[3],
            "closed": row[4]
        }
    return result

async def add_warning(guild_id: str, user_id: str, moderator_id: str, reason: str):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES ($1, $2, $3, $4)",
        guild_id, user_id, moderator_id, reason
    )
    await conn.close()

async def get_warnings(guild_id: str, user_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id = $1 AND user_id = $2 ORDER BY created_at DESC",
        guild_id, user_id
    )
    await conn.close()
    return rows

async def clear_warnings(guild_id: str, user_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM warnings WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
    await conn.close()

# ================= ВСЕ ЯЗЫКИ МИРА =================
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

# ================= БОТ =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True  # нужно для part of ban/kick audit-логов, безопасно включить

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command("help")

data_store = {}
active_tickets = {}

# ================= КНОПКИ ПЕРЕВОДА =================
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

# ================= КНОПКИ ТИКЕТОВ =================
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

        category = discord.utils.get(interaction.guild.categories, name="Tickets")
        if not category:
            category = await interaction.guild.create_category("Tickets")

        channel = await interaction.guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            category=category,
            topic=f"Ticket from {interaction.user.name}",
            overwrites={
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )

        ticket_id = str(channel.id)
        active_tickets[ticket_id] = {
            "ticket_id": ticket_id,
            "channel_id": str(channel.id),
            "creator_id": str(interaction.user.id),
            "topic": "Support",
            "closed": False
        }
        await save_ticket(active_tickets[ticket_id])
        bot.add_view(TicketView(ticket_id))  # регистрируем на случай рестарта

        embed = discord.Embed(
            title="🎫 Ticket Created",
            description=f"**Created by:** {interaction.user.mention}\n**Support will assist you shortly.**",
            color=discord.Color.blue()
        )
        view = TicketView(ticket_id)
        await channel.send(embed=embed, view=view)

        await interaction.response.send_message(f"✅ Ticket created! Go to {channel.mention}", ephemeral=True)

class TicketView(ui.View):
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        close_btn = ui.Button(
            label="🔒 Close Ticket",
            style=discord.ButtonStyle.danger,
            custom_id=f"close_ticket_{ticket_id}"
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def close_callback(self, interaction: Interaction):
        if self.ticket_id not in active_tickets:
            await interaction.response.send_message("❌ Ticket not found.", ephemeral=True)
            return

        ticket = active_tickets[self.ticket_id]
        if ticket["closed"]:
            await interaction.response.send_message("❌ Ticket already closed.", ephemeral=True)
            return

        if interaction.user.id != int(ticket["creator_id"]) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
            return

        ticket["closed"] = True
        await save_ticket(ticket)
        await interaction.response.send_message("🔒 Ticket closed. Deleting in 5s...")
        await asyncio.sleep(5)

        channel = interaction.channel
        if channel:
            await channel.delete()

# ================= ПРЕФИКСНЫЕ КОМАНДЫ =================
@bot.command(name="news")
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

    category = discord.utils.get(ctx.guild.categories, name="Tickets")
    if not category:
        category = await ctx.guild.create_category("Tickets")

    channel = await ctx.guild.create_text_channel(
        f"ticket-{ctx.author.name}",
        category=category,
        topic=f"Ticket from {ctx.author.name}: {topic}",
        overwrites={
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
    )

    ticket_id = str(channel.id)
    active_tickets[ticket_id] = {
        "ticket_id": ticket_id,
        "channel_id": str(channel.id),
        "creator_id": str(ctx.author.id),
        "topic": topic,
        "closed": False
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

    if ctx.author.id != int(ticket["creator_id"]) and not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You don't have permission.")
        return

    ticket["closed"] = True
    await save_ticket(ticket)
    await ctx.send("🔒 Ticket closed. Deleting in 5s...")
    await asyncio.sleep(5)
    await ctx.channel.delete()

@bot.command(name="ping")
async def ping_prefix(ctx):
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")

# ---- ручной ресинк слеш-команд (owner-only) ----
# Ничего настраивать не нужно: бот и так синкает команды глобально при каждом
# запуске (см. on_ready). Эта команда — просто "сделать это ещё раз прямо сейчас",
# без ожидания рестарта. Если задан GUILD_ID — дополнительно синкает мгновенно
# в этот сервер для более быстрого тестирования.
@bot.command(name="sync")
@commands.is_owner()
async def sync_prefix(ctx):
    synced_global = await bot.tree.sync()
    msg = f"✅ Synced {len(synced_global)} commands globally (может занять несколько минут на клиентах)."

    if TEST_GUILD is not None:
        bot.tree.copy_global_to(guild=TEST_GUILD)
        synced_guild = await bot.tree.sync(guild=TEST_GUILD)
        msg += f"\n✅ Also synced {len(synced_guild)} commands to this guild instantly."

    await ctx.send(msg)

@bot.command(name="commands")
async def commands_prefix(ctx):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`!news` — Publish news\n`!lang_add` — Add translation\n`!lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`!ticket_setup` — Setup ticket system\n`!ticket` — Create ticket\n`!ticket_close` — Close ticket", inline=False)
    embed.add_field(
        name="🛡️ Moderation",
        value="`!kick` `!ban` `!unban` `!mute` `!unmute` `!warn` `!warnings` `!clearwarnings` `!clear`",
        inline=False
    )
    embed.add_field(name="ℹ️ Other", value="`!say` — Make bot say something\n`!ping` — Check latency\n`!sync` — Re-sync slash commands (owner)\n`!commands` — This menu", inline=False)
    await ctx.send(embed=embed)

# ================= МОДЕРАЦИЯ: ПРЕФИКСНЫЕ =================
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
    await member.kick(reason=f"{reason} | by {ctx.author}")
    await ctx.send(f"👢 **{member}** was kicked. Reason: {reason}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You can't ban someone with an equal or higher role.")
        return
    await member.ban(reason=f"{reason} | by {ctx.author}", delete_message_days=0)
    await ctx.send(f"🔨 **{member}** was banned. Reason: {reason}")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban_prefix(ctx, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"✅ **{user}** was unbanned.")
    except discord.NotFound:
        await ctx.send("❌ User is not banned or does not exist.")

@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def mute_prefix(ctx, member: discord.Member, minutes: int, *, reason: str = "No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        await ctx.send("❌ You can't mute someone with an equal or higher role.")
        return
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=f"{reason} | by {ctx.author}")
    await ctx.send(f"🔇 **{member}** muted for {fmt_duration(duration)}. Reason: {reason}")

@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def unmute_prefix(ctx, member: discord.Member):
    await member.timeout(None, reason=f"Unmuted by {ctx.author}")
    await ctx.send(f"🔊 **{member}** was unmuted.")

@bot.command(name="warn")
@commands.has_permissions(moderate_members=True)
async def warn_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await add_warning(str(ctx.guild.id), str(member.id), str(ctx.author.id), reason)
    await ctx.send(f"⚠️ **{member}** was warned. Reason: {reason}")
    try:
        await member.send(f"⚠️ You were warned in **{ctx.guild.name}**. Reason: {reason}")
    except discord.Forbidden:
        pass

@bot.command(name="warnings")
async def warnings_prefix(ctx, member: discord.Member = None):
    member = member or ctx.author
    rows = await get_warnings(str(ctx.guild.id), str(member.id))
    if not rows:
        await ctx.send(f"✅ **{member}** has no warnings.")
        return
    embed = discord.Embed(title=f"⚠️ Warnings for {member}", color=discord.Color.orange())
    for r in rows[:15]:
        mod = ctx.guild.get_member(int(r["moderator_id"]))
        embed.add_field(
            name=f"#{r['id']} — {r['created_at'].strftime('%Y-%m-%d %H:%M')}",
            value=f"By: {mod.mention if mod else r['moderator_id']}\nReason: {r['reason']}",
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
    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 включает саму команду
    msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.")
    await asyncio.sleep(3)
    await msg.delete()

# ================= СЛЭШ-КОМАНДЫ =================
@bot.tree.command(name="news", description="Publish a news post")
@app_commands.describe(
    en="English text (primary)",
    ru="Russian translation (optional)",
    es="Spanish translation (optional)",
    fr="French translation (optional)",
    de="German translation (optional)"
)
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

    category = discord.utils.get(interaction.guild.categories, name="Tickets")
    if not category:
        category = await interaction.guild.create_category("Tickets")

    channel = await interaction.guild.create_text_channel(
        f"ticket-{interaction.user.name}",
        category=category,
        topic=f"Ticket from {interaction.user.name}: {topic}",
        overwrites={
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
    )

    ticket_id = str(channel.id)
    active_tickets[ticket_id] = {
        "ticket_id": ticket_id,
        "channel_id": str(channel.id),
        "creator_id": str(interaction.user.id),
        "topic": topic,
        "closed": False
    }
    await save_ticket(active_tickets[ticket_id])
    bot.add_view(TicketView(ticket_id))

    embed = discord.Embed(title="🎫 New Ticket", description=f"**Topic:** {topic}\n**Created by:** {interaction.user.mention}", color=discord.Color.blue())
    view = TicketView(ticket_id)
    await channel.send(embed=embed, view=view)
    await interaction.followup.send(f"✅ Ticket created! Go to {channel.mention}", ephemeral=True)

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

    if interaction.user.id != int(ticket["creator_id"]) and not interaction.user.guild_permissions.administrator:
        await interaction.followup.send("❌ You don't have permission.", ephemeral=True)
        return

    ticket["closed"] = True
    await save_ticket(ticket)
    await interaction.channel.send("🔒 Ticket closed. Deleting in 5s...")
    await asyncio.sleep(5)
    await interaction.channel.delete()
    await interaction.followup.send("✅ Ticket closed.", ephemeral=True)

@bot.tree.command(name="ping", description="Check bot latency")
async def slash_ping(interaction: Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms", ephemeral=True)

@bot.tree.command(name="commands", description="Show all commands")
async def slash_commands(interaction: Interaction):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`/news` — Publish news\n`/lang_add` — Add translation\n`/lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket_setup` — Setup ticket system\n`/ticket` — Create ticket\n`/ticket_close` — Close ticket", inline=False)
    embed.add_field(
        name="🛡️ Moderation",
        value="`/kick` `/ban` `/unban` `/mute` `/unmute` `/warn` `/warnings` `/clearwarnings` `/clear`",
        inline=False
    )
    embed.add_field(name="ℹ️ Other", value="`/say` — Make bot say something\n`/ping` — Check latency\n`/commands` — This menu", inline=False)
    embed.add_field(name="📝 Prefix commands", value="Use `!` before commands (e.g. `!news`)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= МОДЕРАЦИЯ: СЛЭШ =================
@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(member="Who to kick", reason="Reason")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You can't kick someone with an equal or higher role.", ephemeral=True)
        return
    await member.kick(reason=f"{reason} | by {interaction.user}")
    await interaction.response.send_message(f"👢 **{member}** was kicked. Reason: {reason}")

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Who to ban", reason="Reason")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You can't ban someone with an equal or higher role.", ephemeral=True)
        return
    await member.ban(reason=f"{reason} | by {interaction.user}", delete_message_days=0)
    await interaction.response.send_message(f"🔨 **{member}** was banned. Reason: {reason}")

@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="User ID to unban")
@app_commands.default_permissions(ban_members=True)
async def slash_unban(interaction: Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ **{user}** was unbanned.")
    except (discord.NotFound, ValueError):
        await interaction.response.send_message("❌ User is not banned or ID is invalid.", ephemeral=True)

@bot.tree.command(name="mute", description="Timeout a member")
@app_commands.describe(member="Who to mute", minutes="Duration in minutes", reason="Reason")
@app_commands.default_permissions(moderate_members=True)
async def slash_mute(interaction: Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You can't mute someone with an equal or higher role.", ephemeral=True)
        return
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=f"{reason} | by {interaction.user}")
    await interaction.response.send_message(f"🔇 **{member}** muted for {fmt_duration(duration)}. Reason: {reason}")

@bot.tree.command(name="unmute", description="Remove a timeout")
@app_commands.describe(member="Who to unmute")
@app_commands.default_permissions(moderate_members=True)
async def slash_unmute(interaction: Interaction, member: discord.Member):
    await member.timeout(None, reason=f"Unmuted by {interaction.user}")
    await interaction.response.send_message(f"🔊 **{member}** was unmuted.")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Who to warn", reason="Reason")
@app_commands.default_permissions(moderate_members=True)
async def slash_warn(interaction: Interaction, member: discord.Member, reason: str = "No reason provided"):
    await add_warning(str(interaction.guild.id), str(member.id), str(interaction.user.id), reason)
    await interaction.response.send_message(f"⚠️ **{member}** was warned. Reason: {reason}")
    try:
        await member.send(f"⚠️ You were warned in **{interaction.guild.name}**. Reason: {reason}")
    except discord.Forbidden:
        pass

@bot.tree.command(name="warnings", description="Show warnings for a member")
@app_commands.describe(member="Member to check")
async def slash_warnings(interaction: Interaction, member: discord.Member = None):
    member = member or interaction.user
    rows = await get_warnings(str(interaction.guild.id), str(member.id))
    if not rows:
        await interaction.response.send_message(f"✅ **{member}** has no warnings.", ephemeral=True)
        return
    embed = discord.Embed(title=f"⚠️ Warnings for {member}", color=discord.Color.orange())
    for r in rows[:15]:
        mod = interaction.guild.get_member(int(r["moderator_id"]))
        embed.add_field(
            name=f"#{r['id']} — {r['created_at'].strftime('%Y-%m-%d %H:%M')}",
            value=f"By: {mod.mention if mod else r['moderator_id']}\nReason: {r['reason']}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member")
@app_commands.describe(member="Member to clear")
@app_commands.default_permissions(administrator=True)
async def slash_clearwarnings(interaction: Interaction, member: discord.Member):
    await clear_warnings(str(interaction.guild.id), str(member.id))
    await interaction.response.send_message(f"🧹 Cleared all warnings for **{member}**.")

@bot.tree.command(name="clear", description="Bulk delete messages in this channel")
@app_commands.describe(amount="How many messages to delete (max 200)")
@app_commands.default_permissions(manage_messages=True)
async def slash_clear(interaction: Interaction, amount: app_commands.Range[int, 1, 200]):
    await interaction.response.defer(ephemeral=True, thinking=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

# ================= ВОССТАНОВЛЕНИЕ =================
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
            bot.add_view(TicketView(ticket_id))  # чтобы кнопка "Close" работала после рестарта
            print(f"✅ Restored ticket {ticket_id}")

# ================= СОБЫТИЯ =================
@bot.event
async def on_ready():
    global data_store

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("SELECT 1")
        await conn.close()
        print("✅ PostgreSQL connected!")
    except Exception as e:
        print(f"❌ DB error: {e}")
        return

    await init_db()
    data_store = await load_all_translations()

    # регистрируем persistent view для кнопки "Apply" тикет-панели (не зависит от message_id)
    bot.add_view(TicketApplyView())

    await restore_tickets()
    await restore_news_messages()

    # СИНХРОНИЗАЦИЯ СЛЭШ-КОМАНД
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
    print("❓ Use !commands or /commands")

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

# ================= ЗАПУСК =================
if __name__ == "__main__":
    bot.run(TOKEN)

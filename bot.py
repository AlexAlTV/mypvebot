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
            user_id TEXT,
            guild_id TEXT,
            reason TEXT,
            moderator_id TEXT,
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
        except:
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

# ================= ФЛАГИ =================
FLAGS = {
    "en": "🇬🇧", "ru": "🇷🇺", "es": "🇪🇸", "fr": "🇫🇷",
    "de": "🇩🇪", "ja": "🇯🇵", "it": "🇮🇹", "pt": "🇵🇹",
    "nl": "🇳🇱", "pl": "🇵🇱", "tr": "🇹🇷", "vi": "🇻🇳",
    "th": "🇹🇭", "id": "🇮🇩", "ms": "🇲🇾", "cs": "🇨🇿",
    "hu": "🇭🇺", "sv": "🇸🇪", "no": "🇳🇴", "fi": "🇫🇮",
    "da": "🇩🇰", "ro": "🇷🇴", "bg": "🇧🇬", "uk": "🇺🇦",
    "el": "🇬🇷", "he": "🇮🇱", "ar": "🇸🇦", "hi": "🇮🇳",
    "ko": "🇰🇷", "zh": "🇨🇳"
}

def get_flag(lang_code: str) -> str:
    return FLAGS.get(lang_code, "🌍")

# ================= БОТ =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command("help")

data_store = {}
active_tickets = {}

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

# ================= ПРЕФИКСНЫЕ КОМАНДЫ =================

# --- НОВОСТИ ---
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

# --- ТИКЕТЫ ---
@bot.command(name="ticket_setup")
@commands.has_permissions(administrator=True)
async def ticket_setup(ctx):
    """Setup the ticket system with Apply button"""
    embed = discord.Embed(
        title="🎫 Join MyPvE",
        description="**Open a ticket!**\n\n**Requirements:**\nSilver 3k wins\nGold 1k wins\nPlat+ bypass",
        color=discord.Color.blue()
    )
    view = TicketApplyView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()

# --- МОДЕРАЦИЯ ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(
            title="👢 Kicked",
            description=f"{member.mention} has been kicked.\n**Reason:** {reason}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to kick this member.")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
        embed = discord.Embed(
            title="🔨 Banned",
            description=f"{member.mention} has been banned.\n**Reason:** {reason}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to ban this member.")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, member_name: str):
    try:
        banned_users = await ctx.guild.bans()
        for ban_entry in banned_users:
            user = ban_entry.user
            if str(user) == member_name or str(user.name) == member_name:
                await ctx.guild.unban(user)
                embed = discord.Embed(
                    title="✅ Unbanned",
                    description=f"{user.mention} has been unbanned.",
                    color=discord.Color.green()
                )
                await ctx.send(embed=embed)
                return
        await ctx.send("❌ User not found in ban list.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unban.")

@bot.command(name="mute")
@commands.has_permissions(manage_messages=True)
async def mute(ctx, member: discord.Member, duration: str = "10m", *, reason: str = "No reason provided"):
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1]
        amount = int(duration[:-1])
        seconds = amount * time_units[unit]
    except:
        seconds = 600
    
    try:
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False)
        
        await member.add_roles(muted_role, reason=reason)
        
        embed = discord.Embed(
            title="🔇 Muted",
            description=f"{member.mention} has been muted for {duration}.\n**Reason:** {reason}",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        
        await asyncio.sleep(seconds)
        await member.remove_roles(muted_role)
        
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to mute this member.")

@bot.command(name="unmute")
@commands.has_permissions(manage_messages=True)
async def unmute(ctx, member: discord.Member):
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        await ctx.send("❌ Muted role not found.")
        return
    
    try:
        await member.remove_roles(muted_role)
        embed = discord.Embed(
            title="🔊 Unmuted",
            description=f"{member.mention} has been unmuted.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unmute this member.")

@bot.command(name="warn")
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO warnings (user_id, guild_id, reason, moderator_id) VALUES ($1, $2, $3, $4)",
            str(member.id), str(ctx.guild.id), reason, str(ctx.author.id)
        )
        await conn.close()
        
        embed = discord.Embed(
            title="⚠️ Warning",
            description=f"{member.mention} has been warned.\n**Reason:** {reason}",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="warnings")
@commands.has_permissions(manage_messages=True)
async def warnings(ctx, member: discord.Member):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch(
            "SELECT reason, moderator_id, created_at FROM warnings WHERE user_id = $1 AND guild_id = $2",
            str(member.id), str(ctx.guild.id)
        )
        await conn.close()
        
        if not rows:
            await ctx.send(f"✅ {member.mention} has no warnings.")
            return
        
        embed = discord.Embed(
            title=f"⚠️ Warnings for {member.name}",
            color=discord.Color.orange()
        )
        for i, row in enumerate(rows[:10], 1):
            mod = await bot.fetch_user(int(row[1]))
            embed.add_field(
                name=f"Warning #{i}",
                value=f"**Reason:** {row[0]}\n**Moderator:** {mod.mention}\n**Date:** {row[2].strftime('%Y-%m-%d %H:%M')}",
                inline=False
            )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    if amount < 1 or amount > 100:
        await ctx.send("❌ Amount must be between 1 and 100.")
        return
    
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"✅ Deleted {len(deleted) - 1} messages.")
        await asyncio.sleep(3)
        await msg.delete()
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to delete messages.")

@bot.command(name="ping")
async def ping_prefix(ctx):
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")

@bot.command(name="commands")
async def commands_prefix(ctx):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`!news` — Publish news\n`!lang_add` — Add translation\n`!lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`!ticket_setup` — Setup ticket system\n`!ticket` — Create ticket (legacy)", inline=False)
    embed.add_field(name="🛠️ Moderation", value="`!kick` — Kick member\n`!ban` — Ban member\n`!unban` — Unban member\n`!mute` — Mute member\n`!unmute` — Unmute member\n`!warn` — Warn member\n`!warnings` — Check warnings\n`!clear` — Clear messages", inline=False)
    embed.add_field(name="ℹ️ Other", value="`!ping` — Check latency\n`!commands` — This menu", inline=False)
    await ctx.send(embed=embed)

# ================= СЛЭШ-КОМАНДЫ =================

# --- НОВОСТИ (SLASH) ---
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

# --- ТИКЕТЫ (SLASH) ---
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
async def slash_ticket(interaction: Interaction, topic: str = "General support"):
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

# --- МОДЕРАЦИЯ (SLASH) ---
@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason for kick")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: Interaction, member: discord.Member, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(
            title="👢 Kicked",
            description=f"{member.mention} has been kicked.\n**Reason:** {reason}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to kick this member.", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Reason for ban")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: Interaction, member: discord.Member, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
        embed = discord.Embed(
            title="🔨 Banned",
            description=f"{member.mention} has been banned.\n**Reason:** {reason}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to ban this member.", ephemeral=True)

@bot.tree.command(name="mute", description="Mute a member")
@app_commands.describe(
    member="Member to mute",
    duration="Duration (10m, 1h, 1d, etc.)",
    reason="Reason for mute"
)
@app_commands.default_permissions(manage_messages=True)
async def slash_mute(interaction: Interaction, member: discord.Member, duration: str = "10m", reason: str = "No reason provided"):
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1]
        amount = int(duration[:-1])
        seconds = amount * time_units[unit]
    except:
        seconds = 600
    
    try:
        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await interaction.guild.create_role(name="Muted")
            for channel in interaction.guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False)
        
        await member.add_roles(muted_role, reason=reason)
        
        embed = discord.Embed(
            title="🔇 Muted",
            description=f"{member.mention} has been muted for {duration}.\n**Reason:** {reason}",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)
        
        await asyncio.sleep(seconds)
        await member.remove_roles(muted_role)
        
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to mute this member.", ephemeral=True)

@bot.tree.command(name="unmute", description="Unmute a member")
@app_commands.describe(member="Member to unmute")
@app_commands.default_permissions(manage_messages=True)
async def slash_unmute(interaction: Interaction, member: discord.Member):
    muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not muted_role:
        await interaction.response.send_message("❌ Muted role not found.", ephemeral=True)
        return
    
    try:
        await member.remove_roles(muted_role)
        embed = discord.Embed(
            title="🔊 Unmuted",
            description=f"{member.mention} has been unmuted.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unmute this member.", ephemeral=True)

@bot.tree.command(name="clear", description="Clear messages")
@app_commands.describe(amount="Number of messages to clear (1-100)")
@app_commands.default_permissions(manage_messages=True)
async def slash_clear(interaction: Interaction, amount: int = 10):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("❌ Amount must be between 1 and 100.", ephemeral=True)
        return
    
    try:
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Deleted {len(deleted)} messages.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to delete messages.", ephemeral=True)

@bot.tree.command(name="ping", description="Check bot latency")
async def slash_ping(interaction: Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms", ephemeral=True)

@bot.tree.command(name="commands", description="Show all commands")
async def slash_commands(interaction: Interaction):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`/news` — Publish news\n`/lang_add` — Add translation\n`/lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket_setup` — Setup ticket system\n`/ticket` — Create ticket\n`/ticket_close` — Close ticket", inline=False)
    embed.add_field(name="🛠️ Moderation", value="`/kick` — Kick member\n`/ban` — Ban member\n`/mute` — Mute member\n`/unmute` — Unmute member\n`/clear` — Clear messages", inline=False)
    embed.add_field(name="ℹ️ Other", value="`/ping` — Check latency\n`/commands` — This menu", inline=False)
    embed.add_field(name="📝 Prefix commands", value="Use `!` before commands (e.g. `!news`)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= LEGACY TICKET (PREFIX) =================
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
                    except:
                        continue
        except Exception as e:
            print(f"❌ Could not restore news {msg_id}: {e}")

async def restore_tickets():
    tickets = await load_tickets()
    for ticket_id, ticket_data in tickets.items():
        if not ticket_data["closed"]:
            active_tickets[ticket_id] = ticket_data
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
    await restore_tickets()
    await restore_news_messages()

    await bot.tree.sync()
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

# ================= ЗАПУСК =================
if __name__ == "__main__":
    bot.run(TOKEN)

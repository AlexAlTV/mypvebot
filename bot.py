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

DEFAULT_PREFIX = "!"

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
            creator_name TEXT,
            topic TEXT,
            closed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ticket_logs (
            id SERIAL PRIMARY KEY,
            ticket_id TEXT,
            action TEXT,
            user_id TEXT,
            user_name TEXT,
            details TEXT,
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
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id TEXT PRIMARY KEY,
            prefix TEXT DEFAULT '!',
            ticket_category TEXT DEFAULT 'Tickets',
            ticket_log_channel TEXT,
            mod_log_channel TEXT,
            muted_role_name TEXT DEFAULT 'Muted',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.close()
    print("✅ Tables created")

async def get_guild_settings(guild_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT * FROM guild_settings WHERE guild_id = $1",
        guild_id
    )
    await conn.close()
    if not row:
        # Создаем настройки по умолчанию
        return await create_guild_settings(guild_id)
    return dict(row)

async def create_guild_settings(guild_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO guild_settings (guild_id) VALUES ($1)",
        guild_id
    )
    await conn.close()
    return {
        "guild_id": guild_id,
        "prefix": DEFAULT_PREFIX,
        "ticket_category": "Tickets",
        "ticket_log_channel": None,
        "mod_log_channel": None,
        "muted_role_name": "Muted"
    }

async def update_guild_settings(guild_id: str, settings: dict):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        """UPDATE guild_settings SET 
           prefix = $1, 
           ticket_category = $2, 
           ticket_log_channel = $3, 
           mod_log_channel = $4,
           muted_role_name = $5,
           updated_at = CURRENT_TIMESTAMP
           WHERE guild_id = $6""",
        settings.get("prefix", DEFAULT_PREFIX),
        settings.get("ticket_category", "Tickets"),
        settings.get("ticket_log_channel"),
        settings.get("mod_log_channel"),
        settings.get("muted_role_name", "Muted"),
        guild_id
    )
    await conn.close()

# ================= ВСЕ ЯЗЫКИ МИРА =================
FLAGS = {
    # Африка
    "af": "🇿🇦",  # Африкаанс
    "am": "🇪🇹",  # Амхарский
    "ar": "🇸🇦",  # Арабский
    "az": "🇦🇿",  # Азербайджанский
    # Азия
    "bn": "🇧🇩",  # Бенгальский
    "zh": "🇨🇳",  # Китайский
    "zh-tw": "🇹🇼",  # Китайский (Тайвань)
    "zh-hk": "🇭🇰",  # Китайский (Гонконг)
    "hi": "🇮🇳",  # Хинди
    "id": "🇮🇩",  # Индонезийский
    "ja": "🇯🇵",  # Японский
    "jv": "🇮🇩",  # Яванский
    "kn": "🇮🇳",  # Каннада
    "ko": "🇰🇷",  # Корейский
    "ml": "🇮🇳",  # Малаялам
    "mr": "🇮🇳",  # Маратхи
    "ms": "🇲🇾",  # Малайский
    "my": "🇲🇲",  # Бирманский
    "ne": "🇳🇵",  # Непальский
    "ta": "🇮🇳",  # Тамильский
    "te": "🇮🇳",  # Телугу
    "th": "🇹🇭",  # Тайский
    "ur": "🇵🇰",  # Урду
    "vi": "🇻🇳",  # Вьетнамский
    # Европа
    "bg": "🇧🇬",  # Болгарский
    "cs": "🇨🇿",  # Чешский
    "da": "🇩🇰",  # Датский
    "nl": "🇳🇱",  # Голландский
    "en": "🇬🇧",  # Английский
    "en-us": "🇺🇸",  # Английский (США)
    "et": "🇪🇪",  # Эстонский
    "fi": "🇫🇮",  # Финский
    "fr": "🇫🇷",  # Французский
    "de": "🇩🇪",  # Немецкий
    "el": "🇬🇷",  # Греческий
    "he": "🇮🇱",  # Иврит
    "hu": "🇭🇺",  # Венгерский
    "is": "🇮🇸",  # Исландский
    "it": "🇮🇹",  # Итальянский
    "lv": "🇱🇻",  # Латышский
    "lt": "🇱🇹",  # Литовский
    "mk": "🇲🇰",  # Македонский
    "no": "🇳🇴",  # Норвежский
    "pl": "🇵🇱",  # Польский
    "pt": "🇵🇹",  # Португальский
    "pt-br": "🇧🇷",  # Португальский (Бразилия)
    "ro": "🇷🇴",  # Румынский
    "ru": "🇷🇺",  # Русский
    "sr": "🇷🇸",  # Сербский
    "sk": "🇸🇰",  # Словацкий
    "sl": "🇸🇮",  # Словенский
    "es": "🇪🇸",  # Испанский
    "es-mx": "🇲🇽",  # Испанский (Мексика)
    "sv": "🇸🇪",  # Шведский
    "tr": "🇹🇷",  # Турецкий
    "uk": "🇺🇦",  # Украинский
    # Океания
    "mi": "🇳🇿",  # Маори
    # Америка
    "ay": "🇧🇴",  # Аймара
    "qu": "🇵🇪",  # Кечуа
}

def get_flag(lang_code: str) -> str:
    return FLAGS.get(lang_code, "🌍")

# ================= БОТ =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=lambda bot, msg: get_prefix(bot, msg), intents=intents)
bot.remove_command("help")

data_store = {}
active_tickets = {}
guild_settings_cache = {}

async def get_prefix(bot, message):
    if not message.guild:
        return DEFAULT_PREFIX
    
    guild_id = str(message.guild.id)
    if guild_id not in guild_settings_cache:
        settings = await get_guild_settings(guild_id)
        guild_settings_cache[guild_id] = settings
    
    return guild_settings_cache[guild_id].get("prefix", DEFAULT_PREFIX)

async def get_settings(guild_id: str):
    if guild_id not in guild_settings_cache:
        settings = await get_guild_settings(guild_id)
        guild_settings_cache[guild_id] = settings
    return guild_settings_cache[guild_id]

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
        
        settings = await get_settings(str(interaction.guild.id))
        category_name = settings.get("ticket_category", "Tickets")
        
        category = discord.utils.get(interaction.guild.categories, name=category_name)
        if not category:
            category = await interaction.guild.create_category(category_name)
        
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
            "creator_name": interaction.user.name,
            "topic": "Support",
            "closed": False,
            "closed_at": None,
            "created_at": datetime.datetime.now()
        }
        await save_ticket(active_tickets[ticket_id])
        
        await log_ticket_action(
            ticket_id, 
            "created", 
            str(interaction.user.id), 
            interaction.user.name,
            f"Topic: Support"
        )
        
        await send_ticket_log(interaction.guild, ticket_id, "created", interaction.user, "Ticket created")
        
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
        self.add_item(ui.Button(label="📋 Transcript", style=discord.ButtonStyle.secondary, custom_id="transcript", disabled=True))
    
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
        ticket["closed_at"] = datetime.datetime.now()
        await save_ticket(ticket)
        
        await log_ticket_action(
            self.ticket_id, 
            "closed", 
            str(interaction.user.id), 
            interaction.user.name,
            f"Closed by {interaction.user.name}"
        )
        
        await send_ticket_log(interaction.guild, self.ticket_id, "closed", interaction.user, "Ticket closed")
        
        await interaction.response.send_message("🔒 Ticket closed. Deleting in 5s...")
        await asyncio.sleep(5)
        
        channel = interaction.channel
        if channel:
            await channel.delete()

# ================= ФУНКЦИИ ДЛЯ ЛОГОВ =================
async def send_ticket_log(guild, ticket_id: str, action: str, user, details: str):
    settings = await get_settings(str(guild.id))
    log_channel_id = settings.get("ticket_log_channel")
    
    if log_channel_id:
        log_channel = guild.get_channel(int(log_channel_id))
    else:
        log_channel = discord.utils.get(guild.text_channels, name="ticket-logs")
    
    if not log_channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        log_channel = await guild.create_text_channel("ticket-logs", overwrites=overwrites)
    
    embed = discord.Embed(
        title=f"📋 Ticket Log - {action.upper()}",
        color=discord.Color.green() if action == "created" else discord.Color.red(),
        timestamp=datetime.datetime.now()
    )
    embed.add_field(name="Ticket ID", value=f"`{ticket_id}`", inline=True)
    embed.add_field(name="Action", value=action, inline=True)
    embed.add_field(name="User", value=f"{user.mention} ({user.name})", inline=True)
    embed.add_field(name="Details", value=details, inline=False)
    
    await log_channel.send(embed=embed)

async def log_ticket_action(ticket_id: str, action: str, user_id: str, user_name: str, details: str = ""):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO ticket_logs (ticket_id, action, user_id, user_name, details) VALUES ($1, $2, $3, $4, $5)",
        ticket_id, action, user_id, user_name, details
    )
    await conn.close()

async def send_mod_log(guild, action: str, user, moderator, reason: str = ""):
    settings = await get_settings(str(guild.id))
    log_channel_id = settings.get("mod_log_channel")
    
    if not log_channel_id:
        return
    
    log_channel = guild.get_channel(int(log_channel_id))
    if not log_channel:
        return
    
    embed = discord.Embed(
        title=f"🛠️ Moderation Action",
        color=discord.Color.orange(),
        timestamp=datetime.datetime.now()
    )
    embed.add_field(name="Action", value=action, inline=True)
    embed.add_field(name="User", value=f"{user.mention} ({user.name})", inline=True)
    embed.add_field(name="Moderator", value=f"{moderator.mention} ({moderator.name})", inline=True)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    
    await log_channel.send(embed=embed)

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
        # Сортируем языки с приоритетом на английский
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

# ================= НАСТРОЙКИ (SETTINGS COMMANDS) =================
@bot.command(name="setprefix")
@commands.has_permissions(administrator=True)
async def set_prefix(ctx, new_prefix: str):
    """Set custom prefix for the server"""
    if len(new_prefix) > 5:
        await ctx.send("❌ Prefix must be 5 characters or less.")
        return
    
    guild_id = str(ctx.guild.id)
    settings = await get_settings(guild_id)
    settings["prefix"] = new_prefix
    await update_guild_settings(guild_id, settings)
    guild_settings_cache[guild_id] = settings
    
    await ctx.send(f"✅ Prefix changed to `{new_prefix}`")

@bot.command(name="setticketcategory")
@commands.has_permissions(administrator=True)
async def set_ticket_category(ctx, category_name: str):
    """Set the category for tickets"""
    guild_id = str(ctx.guild.id)
    settings = await get_settings(guild_id)
    settings["ticket_category"] = category_name
    await update_guild_settings(guild_id, settings)
    guild_settings_cache[guild_id] = settings
    
    await ctx.send(f"✅ Ticket category changed to `{category_name}`")

@bot.command(name="setticketlog")
@commands.has_permissions(administrator=True)
async def set_ticket_log(ctx, channel: discord.TextChannel = None):
    """Set the channel for ticket logs"""
    if not channel:
        channel = ctx.channel
    
    guild_id = str(ctx.guild.id)
    settings = await get_settings(guild_id)
    settings["ticket_log_channel"] = str(channel.id)
    await update_guild_settings(guild_id, settings)
    guild_settings_cache[guild_id] = settings
    
    await ctx.send(f"✅ Ticket log channel set to {channel.mention}")

@bot.command(name="setmodlog")
@commands.has_permissions(administrator=True)
async def set_mod_log(ctx, channel: discord.TextChannel = None):
    """Set the channel for moderation logs"""
    if not channel:
        channel = ctx.channel
    
    guild_id = str(ctx.guild.id)
    settings = await get_settings(guild_id)
    settings["mod_log_channel"] = str(channel.id)
    await update_guild_settings(guild_id, settings)
    guild_settings_cache[guild_id] = settings
    
    await ctx.send(f"✅ Moderation log channel set to {channel.mention}")

@bot.command(name="setmutedrole")
@commands.has_permissions(administrator=True)
async def set_muted_role(ctx, role_name: str):
    """Set the name of the muted role"""
    guild_id = str(ctx.guild.id)
    settings = await get_settings(guild_id)
    settings["muted_role_name"] = role_name
    await update_guild_settings(guild_id, settings)
    guild_settings_cache[guild_id] = settings
    
    await ctx.send(f"✅ Muted role name changed to `{role_name}`")

@bot.command(name="settings")
@commands.has_permissions(administrator=True)
async def show_settings(ctx):
    """Show current server settings"""
    guild_id = str(ctx.guild.id)
    settings = await get_settings(guild_id)
    
    embed = discord.Embed(
        title="⚙️ Server Settings",
        color=discord.Color.blue()
    )
    embed.add_field(name="Prefix", value=f"`{settings.get('prefix', DEFAULT_PREFIX)}`", inline=True)
    embed.add_field(name="Ticket Category", value=f"`{settings.get('ticket_category', 'Tickets')}`", inline=True)
    embed.add_field(name="Ticket Log Channel", value=f"<#{settings.get('ticket_log_channel')}>" if settings.get('ticket_log_channel') else "Not set", inline=True)
    embed.add_field(name="Mod Log Channel", value=f"<#{settings.get('mod_log_channel')}>" if settings.get('mod_log_channel') else "Not set", inline=True)
    embed.add_field(name="Muted Role", value=f"`{settings.get('muted_role_name', 'Muted')}`", inline=True)
    
    await ctx.send(embed=embed)

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

@bot.command(name="ticket_logs")
@commands.has_permissions(administrator=True)
async def ticket_logs_cmd(ctx, ticket_id: str = None):
    """Show ticket logs. Usage: !ticket_logs [ticket_id]"""
    conn = await asyncpg.connect(DATABASE_URL)
    
    if ticket_id:
        rows = await conn.fetch(
            "SELECT * FROM ticket_logs WHERE ticket_id = $1 ORDER BY created_at DESC",
            ticket_id
        )
        if not rows:
            await ctx.send(f"❌ No logs found for ticket {ticket_id}")
            await conn.close()
            return
        
        embed = discord.Embed(
            title=f"📋 Ticket Logs for {ticket_id}",
            color=discord.Color.blue()
        )
        for row in rows[:20]:
            embed.add_field(
                name=f"{row[2].upper()} - {row[5].strftime('%Y-%m-%d %H:%M')}",
                value=f"**User:** {row[3]}\n**Details:** {row[4] or 'N/A'}",
                inline=False
            )
        await ctx.send(embed=embed)
    else:
        rows = await conn.fetch(
            "SELECT * FROM ticket_logs ORDER BY created_at DESC LIMIT 20"
        )
        if not rows:
            await ctx.send("❌ No logs found.")
            await conn.close()
            return
        
        embed = discord.Embed(
            title="📋 Recent Ticket Logs (Last 20)",
            color=discord.Color.blue()
        )
        for row in rows:
            embed.add_field(
                name=f"{row[2].upper()} - {row[5].strftime('%Y-%m-%d %H:%M')}",
                value=f"**Ticket:** `{row[1]}`\n**User:** {row[3]}\n**Details:** {row[4] or 'N/A'}",
                inline=False
            )
        await ctx.send(embed=embed)
    
    await conn.close()

@bot.command(name="ticket_stats")
@commands.has_permissions(administrator=True)
async def ticket_stats(ctx):
    """Show ticket statistics"""
    conn = await asyncpg.connect(DATABASE_URL)
    
    total = await conn.fetchval("SELECT COUNT(*) FROM tickets")
    open_tickets = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE closed = false")
    closed_tickets = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE closed = true")
    
    top_users = await conn.fetch(
        "SELECT creator_name, COUNT(*) as count FROM tickets GROUP BY creator_name ORDER BY count DESC LIMIT 5"
    )
    
    embed = discord.Embed(
        title="📊 Ticket Statistics",
        color=discord.Color.gold()
    )
    embed.add_field(name="Total Tickets", value=str(total), inline=True)
    embed.add_field(name="Open Tickets", value=str(open_tickets), inline=True)
    embed.add_field(name="Closed Tickets", value=str(closed_tickets), inline=True)
    
    if top_users:
        top_text = "\n".join([f"{row[0]}: {row[1]} tickets" for row in top_users])
        embed.add_field(name="Top Users", value=top_text, inline=False)
    
    await ctx.send(embed=embed)
    await conn.close()

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
        await send_mod_log(ctx.guild, "Kick", member, ctx.author, reason)
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
        await send_mod_log(ctx.guild, "Ban", member, ctx.author, reason)
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
                await send_mod_log(ctx.guild, "Unban", user, ctx.author)
                return
        await ctx.send("❌ User not found in ban list.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unban.")

@bot.command(name="mute")
@commands.has_permissions(manage_messages=True)
async def mute(ctx, member: discord.Member, duration: str = "10m", *, reason: str = "No reason provided"):
    settings = await get_settings(str(ctx.guild.id))
    role_name = settings.get("muted_role_name", "Muted")
    
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1]
        amount = int(duration[:-1])
        seconds = amount * time_units[unit]
    except:
        seconds = 600
    
    try:
        muted_role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not muted_role:
            muted_role = await ctx.guild.create_role(name=role_name)
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False)
        
        await member.add_roles(muted_role, reason=reason)
        
        embed = discord.Embed(
            title="🔇 Muted",
            description=f"{member.mention} has been muted for {duration}.\n**Reason:** {reason}",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        await send_mod_log(ctx.guild, f"Mute ({duration})", member, ctx.author, reason)
        
        await asyncio.sleep(seconds)
        await member.remove_roles(muted_role)
        
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to mute this member.")

@bot.command(name="unmute")
@commands.has_permissions(manage_messages=True)
async def unmute(ctx, member: discord.Member):
    settings = await get_settings(str(ctx.guild.id))
    role_name = settings.get("muted_role_name", "Muted")
    
    muted_role = discord.utils.get(ctx.guild.roles, name=role_name)
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
        await send_mod_log(ctx.guild, "Unmute", member, ctx.author)
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
        await send_mod_log(ctx.guild, "Warning", member, ctx.author, reason)
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
    settings = await get_settings(str(ctx.guild.id))
    prefix = settings.get("prefix", DEFAULT_PREFIX)
    
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value=f"`{prefix}news` — Publish news\n`{prefix}lang_add` — Add translation\n`{prefix}lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value=f"`{prefix}ticket_setup` — Setup ticket system\n`{prefix}ticket` — Create ticket\n`{prefix}ticket_close` — Close ticket\n`{prefix}ticket_logs` — View ticket logs\n`{prefix}ticket_stats` — Ticket statistics", inline=False)
    embed.add_field(name="🛠️ Moderation", value=f"`{prefix}kick` — Kick member\n`{prefix}ban` — Ban member\n`{prefix}unban` — Unban member\n`{prefix}mute` — Mute member\n`{prefix}unmute` — Unmute member\n`{prefix}warn` — Warn member\n`{prefix}warnings` — Check warnings\n`{prefix}clear` — Clear messages", inline=False)
    embed.add_field(name="⚙️ Settings", value=f"`{prefix}setprefix` — Set custom prefix\n`{prefix}setticketcategory` — Set ticket category\n`{prefix}setticketlog` — Set ticket log channel\n`{prefix}setmodlog` — Set mod log channel\n`{prefix}setmutedrole` — Set muted role name\n`{prefix}settings` — Show current settings", inline=False)
    embed.add_field(name="ℹ️ Other", value=f"`{prefix}ping` — Check latency\n`{prefix}commands` — This menu", inline=False)
    await ctx.send(embed=embed)

# ================= СЛЭШ-КОМАНДЫ =================
# (Пропускаем для краткости, но они должны быть аналогичны префиксным)

# ================= LEGACY TICKET =================
@bot.command(name="ticket")
async def ticket_prefix(ctx, *, topic: str = "General support"):
    for tid, data in active_tickets.items():
        if data.get("creator_id") == str(ctx.author.id) and not data.get("closed", False):
            await ctx.send(f"❌ You already have an open ticket.")
            return
    
    settings = await get_settings(str(ctx.guild.id))
    category_name = settings.get("ticket_category", "Tickets")
    
    category = discord.utils.get(ctx.guild.categories, name=category_name)
    if not category:
        category = await ctx.guild.create_category(category_name)
    
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
        "creator_name": ctx.author.name,
        "topic": topic,
        "closed": False,
        "closed_at": None,
        "created_at": datetime.datetime.now()
    }
    await save_ticket(active_tickets[ticket_id])
    
    await log_ticket_action(
        ticket_id, 
        "created", 
        str(ctx.author.id), 
        ctx.author.name,
        f"Topic: {topic}"
    )
    await send_ticket_log(ctx.guild, ticket_id, "created", ctx.author, f"Ticket created: {topic}")
    
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
    ticket["closed_at"] = datetime.datetime.now()
    await save_ticket(ticket)
    
    await log_ticket_action(
        ticket_id, 
        "closed", 
        str(ctx.author.id), 
        ctx.author.name,
        f"Closed by {ctx.author.name}"
    )
    await send_ticket_log(ctx.guild, ticket_id, "closed", ctx.author, "Ticket closed")
    
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

import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands
import json
import os
import asyncio
import asyncpg
import datetime
import re

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

# Используем commands.Bot, он уже содержит tree
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
# Удаляем встроенную команду help
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
    """Publish news with translations"""
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
    """Add translation to news: !lang_add <message_id> <lang> <text>"""
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
    """Show all translations for news"""
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

@bot.command(name="ticket")
async def ticket_prefix(ctx, *, topic: str = "General support"):
    """Create a support ticket"""
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
    """Close the current ticket"""
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
    """Check bot latency"""
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")

# ИЗМЕНЕНО: переименована команда help в commands
@bot.command(name="commands")
async def commands_prefix(ctx):
    """Show all commands"""
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`!news` — Publish news\n`!lang_add` — Add translation\n`!lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`!ticket` — Create ticket\n`!ticket_close` — Close ticket", inline=False)
    embed.add_field(name="ℹ️ Other", value="`!ping` — Check latency\n`!commands` — This menu", inline=False)
    await ctx.send(embed=embed)

# ================= СЛЭШ-КОМАНДЫ =================
# Используем bot.tree вместо создания нового tree
@bot.tree.command(name="news", description="Publish a news post")
@app_commands.describe(
    en="English text (primary)",
    ru="Russian translation (optional)",
    es="Spanish translation (optional)",
    fr="French translation (optional)",
    de="German translation (optional)"
)
async def news_command(
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
async def lang_add(
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
async def lang_list(
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

@bot.tree.command(name="ticket", description="Create a support ticket")
@app_commands.describe(topic="Ticket topic")
async def ticket_command(interaction: Interaction, topic: str):
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
async def ticket_close_command(interaction: Interaction):
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
async def ping(interaction: Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms", ephemeral=True)

# ИЗМЕНЕНО: переименована слэш-команда help в commands
@bot.tree.command(name="commands", description="Show all commands")
async def commands_cmd(interaction: Interaction):
    embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.gold())
    embed.add_field(name="📰 News", value="`/news` — Publish news\n`/lang_add` — Add translation\n`/lang_list` — List translations", inline=False)
    embed.add_field(name="🎫 Tickets", value="`/ticket` — Create ticket\n`/ticket_close` — Close ticket", inline=False)
    embed.add_field(name="ℹ️ Other", value="`/ping` — Check latency\n`/commands` — This menu", inline=False)
    embed.add_field(name="📝 Prefix commands", value="Use `!` before commands (e.g. `!news`)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= ВОССТАНОВЛЕНИЕ СООБЩЕНИЙ =================
async def restore_news_messages():
    """Restore news messages and their buttons"""
    for msg_id, data in data_store.items():
        try:
            # Try to find the message in all channels
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
    """Restore active tickets from database"""
    tickets = await load_tickets()
    for ticket_id, ticket_data in tickets.items():
        if not ticket_data["closed"]:
            active_tickets[ticket_id] = ticket_data
            print(f"✅ Restored ticket {ticket_id}")

# ================= ОБРАБОТЧИКИ СОБЫТИЙ =================
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
    
    # Restore tickets
    await restore_tickets()

    # Restore news messages
    await restore_news_messages()

    # Sync slash commands - используем bot.tree
    await bot.tree.sync()
    await bot.change_presence(status=discord.Status.online)

    print(f"✅ Bot online as {bot.user}")
    print(f"📰 Loaded: {len(data_store)} news")
    print(f"🎫 Loaded: {len(active_tickets)} active tickets")
    print(f"❓ Use !commands or /commands")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Process prefix commands
    await bot.process_commands(message)

# ================= ЗАПУСК =================
if __name__ == "__main__":
    bot.run(TOKEN)

import discord
from discord import ui, Interaction, app_commands
import json
import os
import asyncio
import asyncpg
import datetime
from typing import Optional

# ================= CONFIG =================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Token not found! Set DISCORD_TOKEN")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL not found!")

# ================= DATABASE =================
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            message_id TEXT PRIMARY KEY,
            data JSONB
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id TEXT PRIMARY KEY,
            settings JSONB
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            guild_id TEXT,
            channel_id TEXT,
            creator_id TEXT,
            topic TEXT,
            created_at TIMESTAMP,
            closed BOOLEAN DEFAULT FALSE
        )
    """)
    await conn.close()
    print("✅ All tables created/verified in PostgreSQL")

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

async def get_guild_settings(guild_id: str) -> dict:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT settings FROM settings WHERE guild_id = $1", guild_id)
    await conn.close()
    if row:
        return json.loads(row[0])
    return {
        "language": "en",
        "log_channel": None,
        "prefix": "/",
        "ticket_category": None,
        "mod_role": None,
        "admin_role": None,
        "welcome_channel": None,
        "welcome_message": None,
        "goodbye_channel": None,
        "goodbye_message": None
    }

async def save_guild_settings(guild_id: str, settings: dict):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO settings (guild_id, settings) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET settings = $2",
        guild_id, json.dumps(settings, ensure_ascii=False)
    )
    await conn.close()

# ================= HELPERS =================
def parse_duration(duration_str: str) -> int | None:
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    if not duration_str:
        return None
    try:
        num = int(duration_str[:-1])
        unit = duration_str[-1].lower()
        if unit not in units:
            return None
        return num * units[unit]
    except:
        return None

def get_flag(lang_code: str) -> str:
    flags = {
        "en": "🇬🇧", "es": "🇪🇸", "fr": "🇫🇷", "de": "🇩🇪",
        "ja": "🇯🇵", "pt": "🇵🇹", "ru": "🇷🇺", "zh": "🇨🇳",
        "it": "🇮🇹", "ko": "🇰🇷", "nl": "🇳🇱", "pl": "🇵🇱",
        "tr": "🇹🇷", "vi": "🇻🇳", "th": "🇹🇭", "id": "🇮🇩",
        "ms": "🇲🇾", "cs": "🇨🇿", "hu": "🇭🇺", "sv": "🇸🇪",
        "no": "🇳🇴", "fi": "🇫🇮", "da": "🇩🇰", "ro": "🇷🇴",
        "bg": "🇧🇬", "uk": "🇺🇦", "el": "🇬🇷", "he": "🇮🇱",
        "ar": "🇸🇦", "hi": "🇮🇳", "ur": "🇵🇰", "fa": "🇮🇷",
        "bn": "🇧🇩", "ta": "🇱🇰", "te": "🇮🇳", "kn": "🇮🇳",
        "ml": "🇮🇳", "gu": "🇮🇳", "pa": "🇮🇳", "or": "🇮🇳",
        "as": "🇮🇳", "mr": "🇮🇳", "ne": "🇳🇵", "si": "🇱🇰",
        "my": "🇲🇲", "km": "🇰🇭", "lo": "🇱🇦", "mn": "🇲🇳",
        "ka": "🇬🇪", "hy": "🇦🇲", "az": "🇦🇿", "sq": "🇦🇱",
        "bs": "🇧🇦", "hr": "🇭🇷", "sr": "🇷🇸", "sk": "🇸🇰",
        "sl": "🇸🇮", "et": "🇪🇪", "lv": "🇱🇻", "lt": "🇱🇹",
        "mt": "🇲🇹", "is": "🇮🇸", "ga": "🇮🇪", "cy": "🇬🇧",
        "gd": "🇬🇧", "af": "🇿🇦", "sw": "🇰🇪", "am": "🇪🇹",
        "ha": "🇳🇬", "ig": "🇳🇬", "yo": "🇳🇬", "zu": "🇿🇦",
        "xh": "🇿🇦", "sn": "🇿🇼", "st": "🇱🇸", "mg": "🇲🇬",
        "so": "🇸🇴", "rw": "🇷🇼", "ti": "🇪🇷", "om": "🇪🇹",
        "wo": "🇸🇳", "ff": "🇸🇳", "ln": "🇨🇩", "kg": "🇨🇩",
        "lg": "🇺🇬", "ny": "🇲🇼", "mk": "🇲🇰", "be": "🇧🇾",
        "uz": "🇺🇿", "kk": "🇰🇿", "ky": "🇰🇬", "tg": "🇹🇯",
        "tk": "🇹🇲", "tl": "🇵🇭", "ceb": "🇵🇭", "haw": "🇺🇸",
        "mi": "🇳🇿", "sm": "🇼🇸", "to": "🇹🇴", "fj": "🇫🇯"
    }
    return flags.get(lang_code, "🌍")

# ================= BOT SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
data_store = {}
disabled_commands = set()
active_tickets = {}

# ================= TRANSLATION BUTTONS =================
class PersonalTranslateView(ui.View):
    def __init__(self, message_id: str):
        super().__init__(timeout=3600)
        self.message_id = str(message_id)
        self._add_buttons()

    def _add_buttons(self):
        if self.message_id not in data_store:
            return
        languages = data_store[self.message_id]
        sorted_langs = sorted(languages.keys(), key=lambda x: (x != "en", x))
        for lang_code in sorted_langs:
            button = ui.Button(
                label=lang_code.upper(),
                emoji=get_flag(lang_code),
                style=discord.ButtonStyle.secondary,
                custom_id=f"lang_{lang_code}_{self.message_id}"
            )
            button.callback = self._make_callback(lang_code)
            self.add_item(button)

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

# ================= NEWS COMMANDS =================
@tree.command(name="news", description="Publish a news post (priority: English)")
@app_commands.describe(
    en_text="English text (primary)",
    ru_text="Russian translation (optional)",
    es_text="Spanish translation (optional)",
    fr_text="French translation (optional)",
    de_text="German translation (optional)"
)
async def news_command(
    interaction: Interaction,
    en_text: str,
    ru_text: str = None,
    es_text: str = None,
    fr_text: str = None,
    de_text: str = None
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.sleep(0.5)

    formatted_text = en_text.replace("\\n", "\n")
    message = await interaction.channel.send(formatted_text)
    msg_id = str(message.id)

    data_store[msg_id] = {"en": en_text.replace("\\n", "\n")}
    if ru_text:
        data_store[msg_id]["ru"] = ru_text.replace("\\n", "\n")
    if es_text:
        data_store[msg_id]["es"] = es_text.replace("\\n", "\n")
    if fr_text:
        data_store[msg_id]["fr"] = fr_text.replace("\\n", "\n")
    if de_text:
        data_store[msg_id]["de"] = de_text.replace("\\n", "\n")

    await save_translation(msg_id, data_store[msg_id])
    view = PersonalTranslateView(msg_id)
    await message.edit(view=view)

    await interaction.followup.send(
        "✅ News published. Use buttons below for translations.",
        ephemeral=True
    )

@tree.command(name="lang_add", description="Add a language to an existing news post")
@app_commands.describe(
    message_id="ID of the news message",
    lang_code="Language code (e.g., 'ru', 'es', 'de')",
    text="Translation text"
)
async def lang_add(
    interaction: Interaction,
    message_id: str,
    lang_code: str,
    text: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.sleep(0.5)

    if message_id not in data_store:
        await interaction.followup.send("❌ News post not found.", ephemeral=True)
        return

    data_store[message_id][lang_code] = text.replace("\\n", "\n")
    await save_translation(message_id, data_store[message_id])

    try:
        channel = interaction.channel
        msg = await channel.fetch_message(int(message_id))
        view = PersonalTranslateView(message_id)
        await msg.edit(view=view)
    except Exception as e:
        print(f"⚠️ Failed to update buttons: {e}")

    await interaction.followup.send(
        f"✅ Added {get_flag(lang_code)} `{lang_code}` to news {message_id}",
        ephemeral=True
    )

@tree.command(name="lang_remove", description="Remove a language from a news post")
@app_commands.describe(
    message_id="ID of the news message",
    lang_code="Language code to remove (e.g., 'ru')"
)
async def lang_remove(
    interaction: Interaction,
    message_id: str,
    lang_code: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.sleep(0.5)

    if message_id not in data_store:
        await interaction.followup.send("❌ News post not found.", ephemeral=True)
        return
    if lang_code not in data_store[message_id]:
        await interaction.followup.send(f"❌ Language `{lang_code}` not found.", ephemeral=True)
        return
    if lang_code == "en" and len(data_store[message_id]) == 1:
        await interaction.followup.send("❌ Cannot remove the only language (English).", ephemeral=True)
        return

    del data_store[message_id][lang_code]
    await save_translation(message_id, data_store[message_id])

    try:
        channel = interaction.channel
        msg = await channel.fetch_message(int(message_id))
        view = PersonalTranslateView(message_id)
        await msg.edit(view=view)
    except Exception as e:
        print(f"⚠️ Failed to update buttons: {e}")

    await interaction.followup.send(
        f"✅ Removed language `{lang_code}` from news {message_id}",
        ephemeral=True
    )

@tree.command(name="lang_list", description="Show all languages for a news post")
@app_commands.describe(message_id="ID of the news message")
async def lang_list(
    interaction: Interaction,
    message_id: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.sleep(0.5)

    if message_id not in data_store:
        await interaction.followup.send("❌ News post not found.", ephemeral=True)
        return

    langs = data_store[message_id]
    embed = discord.Embed(
        title=f"📚 Languages for news {message_id}",
        description="\n".join([f"• {get_flag(k)} **{k.upper()}**: {v[:50]}..." for k, v in langs.items()]),
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="list_all", description="Show all saved news IDs (admin)")
async def list_all(interaction: Interaction):
    if not data_store:
        await interaction.response.send_message("❌ No saved news.", ephemeral=True)
        return

    text = "📰 **Saved news:**\n"
    for msg_id in data_store:
        langs = ", ".join(data_store[msg_id].keys())
        text += f"• ID: `{msg_id}` — languages: {langs}\n"

    await interaction.response.send_message(text, ephemeral=True)

@tree.command(name="refresh_buttons", description="Refresh buttons for all news (admin)")
@app_commands.default_permissions(administrator=True)
async def refresh_buttons(interaction: Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    count = 0
    for msg_id in data_store:
        try:
            channel = interaction.channel
            msg = await channel.fetch_message(int(msg_id))
            view = PersonalTranslateView(msg_id)
            await msg.edit(view=view)
            count += 1
        except:
            pass
    await interaction.followup.send(f"✅ Refreshed buttons for {count} news.", ephemeral=True)

# ================= SETTINGS COMMANDS =================
@tree.command(name="settings", description="Show current bot settings")
async def settings_command(interaction: Interaction):
    settings = await get_guild_settings(str(interaction.guild_id))
    embed = discord.Embed(
        title="⚙️ Bot Settings",
        color=discord.Color.blue()
    )
    embed.add_field(name="Language", value=settings.get("language", "en"), inline=True)
    embed.add_field(name="Prefix", value=settings.get("prefix", "/"), inline=True)
    embed.add_field(name="Log Channel", value=f"<#{settings['log_channel']}>" if settings.get("log_channel") else "❌ Not set", inline=True)
    embed.add_field(name="Mod Role", value=f"<@&{settings['mod_role']}>" if settings.get("mod_role") else "❌ Not set", inline=True)
    embed.add_field(name="Admin Role", value=f"<@&{settings['admin_role']}>" if settings.get("admin_role") else "❌ Not set", inline=True)
    embed.add_field(name="Ticket Category", value=settings.get("ticket_category") or "❌ Not set", inline=True)
    embed.add_field(name="Welcome Channel", value=f"<#{settings['welcome_channel']}>" if settings.get("welcome_channel") else "❌ Not set", inline=True)
    embed.add_field(name="Goodbye Channel", value=f"<#{settings['goodbye_channel']}>" if settings.get("goodbye_channel") else "❌ Not set", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="set_language", description="Set bot language")
@app_commands.describe(language_code="Language code (en, ru, es, fr, de, etc.)")
@app_commands.default_permissions(administrator=True)
async def set_language(
    interaction: Interaction,
    language_code: str
):
    settings = await get_guild_settings(str(interaction.guild_id))
    settings["language"] = language_code
    await save_guild_settings(str(interaction.guild_id), settings)
    await interaction.response.send_message(f"✅ Language set to `{language_code}`", ephemeral=True)

@tree.command(name="set_log_channel", description="Set channel for logs")
@app_commands.describe(channel="The channel to send logs to")
@app_commands.default_permissions(administrator=True)
async def set_log_channel(
    interaction: Interaction,
    channel: discord.TextChannel
):
    settings = await get_guild_settings(str(interaction.guild_id))
    settings["log_channel"] = str(channel.id)
    await save_guild_settings(str(interaction.guild_id), settings)
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}", ephemeral=True)

@tree.command(name="set_mod_role", description="Set moderator role")
@app_commands.describe(role="The role for moderators")
@app_commands.default_permissions(administrator=True)
async def set_mod_role(
    interaction: Interaction,
    role: discord.Role
):
    settings = await get_guild_settings(str(interaction.guild_id))
    settings["mod_role"] = str(role.id)
    await save_guild_settings(str(interaction.guild_id), settings)
    await interaction.response.send_message(f"✅ Moderator role set to {role.mention}", ephemeral=True)

@tree.command(name="set_admin_role", description="Set administrator role")
@app_commands.describe(role="The role for administrators")
@app_commands.default_permissions(administrator=True)
async def set_admin_role(
    interaction: Interaction,
    role: discord.Role
):
    settings = await get_guild_settings(str(interaction.guild_id))
    settings["admin_role"] = str(role.id)
    await save_guild_settings(str(interaction.guild_id), settings)
    await interaction.response.send_message(f"✅ Administrator role set to {role.mention}", ephemeral=True)

@tree.command(name="set_prefix", description="Set command prefix")
@app_commands.describe(prefix="New prefix (e.g., '!', '.', '?')")
@app_commands.default_permissions(administrator=True)
async def set_prefix(
    interaction: Interaction,
    prefix: str
):
    settings = await get_guild_settings(str(interaction.guild_id))
    settings["prefix"] = prefix
    await save_guild_settings(str(interaction.guild_id), settings)
    await interaction.response.send_message(f"✅ Prefix set to `{prefix}`", ephemeral=True)

# ================= MODERATION COMMANDS =================
@tree.command(name="say", description="Send a message as the bot")
@app_commands.describe(
    channel="The channel to send the message to",
    text="The message text"
)
@app_commands.default_permissions(manage_messages=True)
async def say_command(
    interaction: Interaction,
    channel: discord.TextChannel,
    text: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await channel.send(text)
    await interaction.followup.send(f"✅ Message sent to {channel.mention}", ephemeral=True)

@tree.command(name="announce", description="Send an announcement (embed)")
@app_commands.describe(
    channel="The channel to send to",
    title="Title of the announcement",
    text="The announcement text",
    color="Color (hex, e.g. #ff0000)"
)
@app_commands.default_permissions(manage_messages=True)
async def announce_command(
    interaction: Interaction,
    channel: discord.TextChannel,
    title: str,
    text: str,
    color: str = "#00ff00"
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        color_int = int(color.replace("#", ""), 16)
    except:
        color_int = 0x00ff00
    embed = discord.Embed(title=title, description=text, color=color_int)
    embed.set_footer(text=f"Published by {interaction.user.display_name}")
    await channel.send(embed=embed)
    await interaction.followup.send(f"✅ Announcement sent to {channel.mention}", ephemeral=True)

@tree.command(name="mute", description="Mute a member")
@app_commands.describe(
    member="The member to mute",
    duration="Duration (e.g. 10m, 1h, 1d)",
    reason="Reason for mute"
)
@app_commands.default_permissions(moderate_members=True)
async def mute_command(
    interaction: Interaction,
    member: discord.Member,
    duration: str,
    reason: str = "No reason provided"
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not interaction.guild.me.guild_permissions.moderate_members:
        await interaction.followup.send("❌ I don't have permission to mute members.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ You cannot mute this member.", ephemeral=True)
        return
    duration_seconds = parse_duration(duration)
    if duration_seconds is None:
        await interaction.followup.send("❌ Invalid duration format. Use: 10m, 1h, 1d", ephemeral=True)
        return
    await member.timeout(duration=datetime.timedelta(seconds=duration_seconds), reason=reason)
    await interaction.followup.send(f"✅ {member.mention} muted for `{duration}`. Reason: {reason}", ephemeral=True)

@tree.command(name="unmute", description="Unmute a member")
@app_commands.describe(member="The member to unmute")
@app_commands.default_permissions(moderate_members=True)
async def unmute_command(
    interaction: Interaction,
    member: discord.Member
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await member.timeout(duration=None)
    await interaction.followup.send(f"✅ {member.mention} unmuted.", ephemeral=True)

@tree.command(name="ban", description="Ban a member")
@app_commands.describe(
    member="The member to ban",
    reason="Reason for ban"
)
@app_commands.default_permissions(ban_members=True)
async def ban_command(
    interaction: Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not interaction.guild.me.guild_permissions.ban_members:
        await interaction.followup.send("❌ I don't have permission to ban members.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ You cannot ban this member.", ephemeral=True)
        return
    await member.ban(reason=reason)
    await interaction.followup.send(f"✅ {member.mention} banned. Reason: {reason}", ephemeral=True)

@tree.command(name="kick", description="Kick a member")
@app_commands.describe(
    member="The member to kick",
    reason="Reason for kick"
)
@app_commands.default_permissions(kick_members=True)
async def kick_command(
    interaction: Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not interaction.guild.me.guild_permissions.kick_members:
        await interaction.followup.send("❌ I don't have permission to kick members.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ You cannot kick this member.", ephemeral=True)
        return
    await member.kick(reason=reason)
    await interaction.followup.send(f"✅ {member.mention} kicked. Reason: {reason}", ephemeral=True)

@tree.command(name="clear", description="Clear messages in the channel")
@app_commands.describe(amount="Number of messages to clear (1-100)")
@app_commands.default_permissions(manage_messages=True)
async def clear_command(
    interaction: Interaction,
    amount: int
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if amount < 1 or amount > 100:
        await interaction.followup.send("❌ Please specify a number between 1 and 100.", ephemeral=True)
        return
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Deleted {len(deleted)} messages.", ephemeral=True)

@tree.command(name="ping", description="Check bot latency")
async def ping_command(interaction: Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latency: {latency} ms", ephemeral=True)

# ================= TICKET COMMANDS =================
@tree.command(name="ticket", description="Create a support ticket")
@app_commands.describe(topic="Topic of the ticket")
async def ticket_command(
    interaction: Interaction,
    topic: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    for ticket_id, data in active_tickets.items():
        if data["creator_id"] == interaction.user.id and not data["closed"]:
            await interaction.followup.send(f"❌ You already have an open ticket: {ticket_id}", ephemeral=True)
            return

    category = discord.utils.get(interaction.guild.categories, name="Tickets")
    if not category:
        category = await interaction.guild.create_category("Tickets")

    channel_name = f"ticket-{interaction.user.name}"
    channel = await interaction.guild.create_text_channel(
        channel_name,
        category=category,
        topic=f"Ticket from {interaction.user.name} | Topic: {topic}",
        overwrites={
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
    )

    ticket_id = str(channel.id)
    active_tickets[ticket_id] = {
        "channel_id": channel.id,
        "creator_id": interaction.user.id,
        "topic": topic,
        "created_at": datetime.datetime.now(),
        "closed": False
    }

    embed = discord.Embed(
        title="🎫 New Ticket",
        description=f"**Topic:** {topic}\n**Created by:** {interaction.user.mention}\n\nUse buttons below.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Ticket ID: {ticket_id}")

    view = ui.View()
    close_button = ui.Button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    add_button = ui.Button(label="➕ Add Member", style=discord.ButtonStyle.primary, custom_id="add_member")
    view.add_item(close_button)
    view.add_item(add_button)

    await channel.send(embed=embed, view=view)
    await interaction.followup.send(f"✅ Ticket created! Go to {channel.mention}", ephemeral=True)

@tree.command(name="ticket_close", description="Close the current ticket")
async def ticket_close_command(interaction: Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    channel = interaction.channel
    ticket_id = str(channel.id)

    if ticket_id not in active_tickets:
        await interaction.followup.send("❌ This channel is not a ticket.", ephemeral=True)
        return

    ticket = active_tickets[ticket_id]
    if ticket["closed"]:
        await interaction.followup.send("❌ This ticket is already closed.", ephemeral=True)
        return

    if interaction.user.id != ticket["creator_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.followup.send("❌ You don't have permission to close this ticket.", ephemeral=True)
        return

    ticket["closed"] = True
    await channel.send("🔒 Ticket closed. Channel will be deleted in 5 seconds...")
    await asyncio.sleep(5)
    await channel.delete()
    await interaction.followup.send("✅ Ticket closed.", ephemeral=True)

# ================= HELP COMMAND =================
@tree.command(name="help", description="Show all available commands")
async def help_command(interaction: Interaction):
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All commands are in English. Translations appear only to you.",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📰 News",
        value="`/news` — Publish a news post\n`/lang_add` — Add translation\n`/lang_remove` — Remove language\n`/lang_list` — List languages\n`/list_all` — Show all news IDs\n`/refresh_buttons` — Refresh buttons for all news (admin)",
        inline=False
    )
    embed.add_field(
        name="⚙️ Settings",
        value="`/settings` — Show current settings\n`/set_language` — Set bot language\n`/set_log_channel` — Set log channel\n`/set_mod_role` — Set moderator role\n`/set_admin_role` — Set admin role\n`/set_prefix` — Set command prefix",
        inline=False
    )
    embed.add_field(
        name="🛡️ Moderation",
        value="`/say` — Send a message\n`/announce` — Send an announcement\n`/mute` — Mute a member\n`/unmute` — Unmute a member\n`/ban` — Ban a member\n`/kick` — Kick a member\n`/clear` — Clear messages",
        inline=False
    )
    embed.add_field(
        name="🎫 Tickets",
        value="`/ticket` — Create a ticket\n`/ticket_close` — Close the current ticket",
        inline=False
    )
    embed.add_field(
        name="ℹ️ Other",
        value="`/ping` — Check bot latency\n`/help` — Show this menu",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= STARTUP =================
@bot.event
async def on_ready():
    global data_store

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("SELECT 1")
        await conn.close()
        print("✅ PostgreSQL connected successfully!")
    except Exception as e:
        print(f"❌ PostgreSQL connection error: {e}")
        return

    await init_db()
    data_store = await load_all_translations()

    await tree.sync()
    await bot.change_presence(status=discord.Status.online)

    print(f"✅ Bot online as {bot.user}")
    print(f"📰 Loaded news: {len(data_store)}")
    print("⚙️ Settings stored in PostgreSQL")
    print("🛡️ Moderation enabled")
    print("🎫 Tickets enabled")
    print("❓ /help — All commands")

bot.run(TOKEN)

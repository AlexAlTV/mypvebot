import discord
from discord import ui, Interaction, app_commands
import json
import os
import asyncio
import asyncpg
import datetime

# ================= КОНФИГ =================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Токен не найден! Установите DISCORD_TOKEN")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не найден!")

# ================= БАЗА ДАННЫХ =================
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            message_id TEXT PRIMARY KEY,
            data JSONB
        )
    """)
    await conn.close()
    print("✅ Таблица news создана/проверена в PostgreSQL")

async def save_translation(message_id: str, data: dict):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO news (message_id, data) VALUES ($1, $2) ON CONFLICT (message_id) DO UPDATE SET data = $2",
        message_id, json.dumps(data, ensure_ascii=False)
    )
    await conn.close()
    print(f"💾 Сохранено в PostgreSQL: {message_id}")

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
    print(f"📥 Загружено из PostgreSQL: {len(result)} записей")
    return result

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
def parse_duration(duration_str: str) -> int | None:
    """Преобразует строку типа '10m' в секунды"""
    units = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800
    }
    
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

# ================= ФЛАГИ =================
FLAGS = {
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

def get_flag(lang_code: str) -> str:
    return FLAGS.get(lang_code, "🌍")

# ================= БОТ =================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
data_store = {}
disabled_commands = set()

# ================= КНОПКИ ПЕРЕВОДА =================
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

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

# ================= КОМАНДЫ ПЕРЕВОДОВ =================
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
        print(f"⚠️ Ошибка обновления кнопок: {e}")

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
        print(f"⚠️ Ошибка обновления кнопок: {e}")

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

# ================= КОМАНДЫ МОДЕРАЦИИ =================

# Команда /say — отправить сообщение от имени бота
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
    if "say" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await channel.send(text)
    await interaction.followup.send(f"✅ Сообщение отправлено в {channel.mention}", ephemeral=True)

# Команда /announce — красивое объявление
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
    if "announce" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    try:
        color_int = int(color.replace("#", ""), 16)
    except:
        color_int = 0x00ff00
    
    embed = discord.Embed(
        title=title,
        description=text,
        color=color_int
    )
    embed.set_footer(text=f"Опубликовано: {interaction.user.display_name}")
    
    await channel.send(embed=embed)
    await interaction.followup.send(f"✅ Объявление отправлено в {channel.mention}", ephemeral=True)

# Команда /mute — выдать мут
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
    if "mute" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if not interaction.guild.me.guild_permissions.moderate_members:
        await interaction.followup.send("❌ У бота нет прав на выдачу мута.", ephemeral=True)
        return
    
    if member.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ Вы не можете замутить этого участника.", ephemeral=True)
        return
    
    duration_seconds = parse_duration(duration)
    if duration_seconds is None:
        await interaction.followup.send("❌ Неправильный формат времени. Используйте: 10m, 1h, 1d", ephemeral=True)
        return
    
    await member.timeout(duration=datetime.timedelta(seconds=duration_seconds), reason=reason)
    await interaction.followup.send(f"✅ {member.mention} замучен на `{duration}`. Причина: {reason}", ephemeral=True)

# Команда /unmute — снять мут
@tree.command(name="unmute", description="Unmute a member")
@app_commands.describe(member="The member to unmute")
@app_commands.default_permissions(moderate_members=True)
async def unmute_command(
    interaction: Interaction,
    member: discord.Member
):
    if "unmute" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    await member.timeout(duration=None)
    await interaction.followup.send(f"✅ Снят мут с {member.mention}", ephemeral=True)

# Команда /ban — забанить участника
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
    if "ban" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if not interaction.guild.me.guild_permissions.ban_members:
        await interaction.followup.send("❌ У бота нет прав на баны.", ephemeral=True)
        return
    
    if member.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ Вы не можете забанить этого участника.", ephemeral=True)
        return
    
    await member.ban(reason=reason)
    await interaction.followup.send(f"✅ {member.mention} забанен. Причина: {reason}", ephemeral=True)

# Команда /kick — кикнуть участника
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
    if "kick" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if not interaction.guild.me.guild_permissions.kick_members:
        await interaction.followup.send("❌ У бота нет прав на кик.", ephemeral=True)
        return
    
    if member.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ Вы не можете кикнуть этого участника.", ephemeral=True)
        return
    
    await member.kick(reason=reason)
    await interaction.followup.send(f"✅ {member.mention} кикнут. Причина: {reason}", ephemeral=True)

# Команда /clear — очистить сообщения
@tree.command(name="clear", description="Clear messages in the channel")
@app_commands.describe(amount="Number of messages to clear (1-100)")
@app_commands.default_permissions(manage_messages=True)
async def clear_command(
    interaction: Interaction,
    amount: int
):
    if "clear" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if amount < 1 or amount > 100:
        await interaction.followup.send("❌ Укажите число от 1 до 100.", ephemeral=True)
        return
    
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Удалено {len(deleted)} сообщений.", ephemeral=True)

# Команда /ping — проверка бота
@tree.command(name="ping", description="Check bot latency")
async def ping_command(interaction: Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Понг! Задержка: {latency} мс", ephemeral=True)

# Команда /disable — отключить команду
@tree.command(name="disable", description="Disable a command temporarily")
@app_commands.describe(command_name="The command name to disable")
@app_commands.default_permissions(administrator=True)
async def disable_command(
    interaction: Interaction,
    command_name: str
):
    if "disable" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    disabled_commands.add(command_name)
    await interaction.response.send_message(f"✅ Команда `{command_name}` отключена.", ephemeral=True)

# Команда /enable — включить команду
@tree.command(name="enable", description="Enable a command")
@app_commands.describe(command_name="The command name to enable")
@app_commands.default_permissions(administrator=True)
async def enable_command(
    interaction: Interaction,
    command_name: str
):
    if "enable" in disabled_commands:
        await interaction.response.send_message("❌ Команда временно отключена.", ephemeral=True)
        return
    if command_name in disabled_commands:
        disabled_commands.remove(command_name)
        await interaction.response.send_message(f"✅ Команда `{command_name}` включена.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ Команда `{command_name}` уже включена.", ephemeral=True)

# ================= ТИКЕТЫ =================

# Конфиг тикетов
TICKET_CATEGORY_NAME = "Tickets"  # Название категории для тикетов
TICKET_LOG_CHANNEL = None  # ID канала для логов (если None — логи в ЛС)

# Хранилище активных тикетов
active_tickets = {}

class TicketView(ui.View):
    """Кнопки управления тикетом"""
    def __init__(self, ticket_id: str, creator_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.creator_id = creator_id

    @ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_button(self, interaction: Interaction, button: ui.Button):
        # Проверяем права
        if interaction.user.id != self.creator_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ У вас нет прав закрыть этот тикет.", ephemeral=True)
            return

        # Запрашиваем подтверждение
        await interaction.response.send_message(
            "⚠️ Вы уверены, что хотите закрыть тикет? Напишите `/ticket confirm` в течение 30 секунд.",
            ephemeral=True
        )
        # Простое подтверждение через повторную команду
        # (Реализовано в отдельной команде /ticket close)

    @ui.button(label="➕ Добавить участника", style=discord.ButtonStyle.primary, custom_id="add_member")
    async def add_member_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Используйте команду `/ticket add @участник`",
            ephemeral=True
        )

# Команда /ticket — создание тикета
@tree.command(name="ticket", description="Create a support ticket")
@app_commands.describe(topic="Topic of the ticket")
async def ticket_command(
    interaction: Interaction,
    topic: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    # Проверяем, есть ли уже открытый тикет у пользователя
    for ticket_id, data in active_tickets.items():
        if data["creator_id"] == interaction.user.id and not data["closed"]:
            await interaction.followup.send(
                f"❌ У вас уже есть открытый тикет: {ticket_id}",
                ephemeral=True
            )
            return

    # Создаём категорию, если её нет
    category = discord.utils.get(interaction.guild.categories, name=TICKET_CATEGORY_NAME)
    if not category:
        category = await interaction.guild.create_category(TICKET_CATEGORY_NAME)

    # Создаём канал для тикета
    channel_name = f"ticket-{interaction.user.name}-{interaction.user.discriminator}"
    channel = await interaction.guild.create_text_channel(
        channel_name,
        category=category,
        topic=f"Тикет от {interaction.user.name} | Тема: {topic}",
        overwrites={
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
    )

    # Сохраняем тикет
    ticket_id = str(channel.id)
    active_tickets[ticket_id] = {
        "channel_id": channel.id,
        "creator_id": interaction.user.id,
        "topic": topic,
        "created_at": datetime.datetime.now(),
        "closed": False
    }

    # Отправляем приветственное сообщение в канал
    embed = discord.Embed(
        title="🎫 Новый тикет",
        description=f"**Тема:** {topic}\n**Создал:** {interaction.user.mention}\n\nИспользуйте кнопки ниже для управления.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"ID тикета: {ticket_id}")

    view = TicketView(ticket_id, interaction.user.id)
    await channel.send(embed=embed, view=view)

    # Логируем создание
    await log_ticket_action(f"🆕 Создан тикет #{ticket_id} | {interaction.user.name} | Тема: {topic}")

    await interaction.followup.send(
        f"✅ Тикет создан! Перейдите в {channel.mention}",
        ephemeral=True
    )

# Команда /ticket close — закрыть тикет
@tree.command(name="ticket_close", description="Close the current ticket")
async def ticket_close_command(interaction: Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)

    channel = interaction.channel
    ticket_id = str(channel.id)

    if ticket_id not in active_tickets:
        await interaction.followup.send("❌ Этот канал не является тикетом.", ephemeral=True)
        return

    ticket = active_tickets[ticket_id]
    if ticket["closed"]:
        await interaction.followup.send("❌ Этот тикет уже закрыт.", ephemeral=True)
        return

    # Проверяем права
    if interaction.user.id != ticket["creator_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.followup.send("❌ У вас нет прав закрыть этот тикет.", ephemeral=True)
        return

    # Закрываем тикет
    ticket["closed"] = True
    await channel.send("🔒 Тикет закрыт. Канал будет удалён через 5 секунд...")

    # Логируем закрытие
    await log_ticket_action(f"🔒 Закрыт тикет #{ticket_id} | {interaction.user.name}")

    # Удаляем канал через 5 секунд
    await asyncio.sleep(5)
    await channel.delete()

    await interaction.followup.send("✅ Тикет закрыт.", ephemeral=True)

# Команда /ticket add — добавить участника
@tree.command(name="ticket_add", description="Add a member to the ticket")
@app_commands.describe(member="The member to add")
async def ticket_add_command(
    interaction: Interaction,
    member: discord.Member
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    channel = interaction.channel
    ticket_id = str(channel.id)

    if ticket_id not in active_tickets:
        await interaction.followup.send("❌ Этот канал не является тикетом.", ephemeral=True)
        return

    ticket = active_tickets[ticket_id]
    if ticket["closed"]:
        await interaction.followup.send("❌ Тикет уже закрыт.", ephemeral=True)
        return

    # Проверяем права
    if interaction.user.id != ticket["creator_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.followup.send("❌ У вас нет прав добавлять участников.", ephemeral=True)
        return

    # Добавляем участника
    await channel.set_permissions(member, read_messages=True, send_messages=True)
    await channel.send(f"👤 {member.mention} добавлен в тикет.")

    await log_ticket_action(f"➕ {member.name} добавлен в тикет #{ticket_id} | {interaction.user.name}")

    await interaction.followup.send(f"✅ {member.mention} добавлен в тикет.", ephemeral=True)

# Команда /ticket remove — удалить участника
@tree.command(name="ticket_remove", description="Remove a member from the ticket")
@app_commands.describe(member="The member to remove")
async def ticket_remove_command(
    interaction: Interaction,
    member: discord.Member
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    channel = interaction.channel
    ticket_id = str(channel.id)

    if ticket_id not in active_tickets:
        await interaction.followup.send("❌ Этот канал не является тикетом.", ephemeral=True)
        return

    ticket = active_tickets[ticket_id]
    if ticket["closed"]:
        await interaction.followup.send("❌ Тикет уже закрыт.", ephemeral=True)
        return

    # Проверяем права
    if interaction.user.id != ticket["creator_id"] and not interaction.user.guild_permissions.administrator:
        await interaction.followup.send("❌ У вас нет прав удалять участников.", ephemeral=True)
        return

    # Нельзя удалить создателя
    if member.id == ticket["creator_id"]:
        await interaction.followup.send("❌ Нельзя удалить создателя тикета.", ephemeral=True)
        return

    # Удаляем участника
    await channel.set_permissions(member, read_messages=False, send_messages=False)
    await channel.send(f"👤 {member.mention} удалён из тикета.")

    await log_ticket_action(f"➖ {member.name} удалён из тикета #{ticket_id} | {interaction.user.name}")

    await interaction.followup.send(f"✅ {member.mention} удалён из тикета.", ephemeral=True)

# Команда /ticket list — список открытых тикетов
@tree.command(name="ticket_list", description="List all open tickets")
@app_commands.default_permissions(administrator=True)
async def ticket_list_command(interaction: Interaction):
    if not active_tickets:
        await interaction.response.send_message("❌ Нет открытых тикетов.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 Открытые тикеты",
        color=discord.Color.blue()
    )

    for ticket_id, data in active_tickets.items():
        if not data["closed"]:
            channel = bot.get_channel(data["channel_id"])
            if channel:
                member = interaction.guild.get_member(data["creator_id"])
                embed.add_field(
                    name=f"#{ticket_id}",
                    value=f"**Создатель:** {member.mention if member else 'Unknown'}\n**Тема:** {data['topic']}\n**Канал:** {channel.mention}",
                    inline=False
                )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= ЛОГИРОВАНИЕ ТИКЕТОВ =================

async def log_ticket_action(message: str):
    """Логирует действие в ЛС создателя или канал логов"""
    try:
        # Отправляем в ЛС создателя бота
        owner = await bot.application_info()
        if owner.owner:
            await owner.owner.send(f"📋 {message}")

        # Если есть канал логов — отправляем туда
        if TICKET_LOG_CHANNEL:
            channel = bot.get_channel(TICKET_LOG_CHANNEL)
            if channel:
                await channel.send(f"📋 {message}")
    except Exception as e:
        print(f"⚠️ Ошибка логирования: {e}")

# ================= ЛОГИРОВАНИЕ СООБЩЕНИЙ В ТИКЕТАХ =================

@bot.event
async def on_message(message: discord.Message):
    # Игнорируем сообщения бота
    if message.author.bot:
        return

    # Проверяем, является ли канал тикетом
    ticket_id = str(message.channel.id)
    if ticket_id in active_tickets and not active_tickets[ticket_id]["closed"]:
        # Логируем сообщение
        log_text = f"💬 [{message.channel.name}] {message.author.name}: {message.content[:500]}"
        if message.attachments:
            log_text += f" 📎 {len(message.attachments)} вложений"

        await log_ticket_action(log_text)

    # Обрабатываем команды (чтобы не сломать другие команды)
    await bot.process_commands(message)
# ================= КОМАНДА /help =================
@tree.command(name="help", description="Show all available commands")
async def help_command(interaction: Interaction):
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All commands are in English. Translations appear only to you.",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📰 News Commands",
        value="`/news` — Publish a news post\n`/lang_add` — Add translation\n`/lang_remove` — Remove language\n`/lang_list` — List languages\n`/list_all` — Show all news IDs",
        inline=False
    )
    embed.add_field(
        name="🛡️ Moderation",
        value="`/say` — Send a message\n`/announce` — Send an announcement\n`/mute` — Mute a member\n`/unmute` — Unmute a member\n`/ban` — Ban a member\n`/kick` — Kick a member\n`/clear` — Clear messages",
        inline=False
    )
    embed.add_field(
        name="⚙️ Admin",
        value="`/disable` — Disable a command\n`/enable` — Enable a command",
        inline=False
    )
    embed.add_field(
        name="ℹ️ Other",
        value="`/ping` — Check bot latency\n`/help` — Show this menu",
        inline=False
    )
    embed.set_footer(text="Click translation buttons under any news post — only you see the result.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= ЗАПУСК =================
@bot.event
async def on_ready():
    global data_store

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("SELECT 1")
        await conn.close()
        print("✅ PostgreSQL подключена успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения к PostgreSQL: {e}")
        return

    await init_db()
    data_store = await load_all_translations()

    await tree.sync()
    await bot.change_presence(status=discord.Status.online)

    print(f"✅ Bot online as {bot.user}")
    print(f"📰 Загружено новостей: {len(data_store)}")
    for msg_id in data_store:
        print(f"   - {msg_id}: {list(data_store[msg_id].keys())}")

    print("📰 /news — Publish (English priority)")
    print("➕ /lang_add — Add language")
    print("➖ /lang_remove — Remove language")
    print("📋 /lang_list — List languages")
    print("🛡️ Moderation commands: /say, /announce, /mute, /unmute, /ban, /kick, /clear")
    print("⚙️ Admin: /disable, /enable")
    print("❓ /help — Show all commands")
    print(f"💾 Data stored in PostgreSQL on Railway")

bot.run(TOKEN)

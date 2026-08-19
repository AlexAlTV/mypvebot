import discord
from discord import ui, Interaction, app_commands
import json
import os
import asyncio
import asyncpg

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
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
data_store = {}

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

# ================= КОМАНДЫ С ГАРАНТИРОВАННЫМ ОТВЕТОМ =================
@tree.command(name="news", description="Publish a news post")
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
    # 🔥 ГАРАНТИРОВАННЫЙ ОТВЕТ - даём боту 15 минут на обработку
    await interaction.response.defer(ephemeral=True, thinking=True)

    # Даём время на переключение контекста
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

# ================= ОСТАЛЬНЫЕ КОМАНДЫ =================
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

@tree.command(name="help", description="Show all available commands")
async def help_command(interaction: Interaction):
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All commands are in English. Translations appear only to you.",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="/news",
        value="Publish a news post (primary: English).\nUsage: `/news en_text:\"Hello\" ru_text:\"Привет\"`",
        inline=False
    )
    embed.add_field(
        name="/lang_add",
        value="Add a translation to an existing news post.\nUsage: `/lang_add message_id:123 lang_code:ru text:\"Привет\"`",
        inline=False
    )
    embed.add_field(
        name="/lang_remove",
        value="Remove a language from a news post.\nUsage: `/lang_remove message_id:123 lang_code:ru`",
        inline=False
    )
    embed.add_field(
        name="/lang_list",
        value="Show all languages for a news post.\nUsage: `/lang_list message_id:123`",
        inline=False
    )
    embed.set_footer(text="Click translation buttons under any news post — only you see the result.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
    print("❓ /help — Show all commands")
    print(f"💾 Data stored in PostgreSQL on Railway")

bot.run(TOKEN)

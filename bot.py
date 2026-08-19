import discord
from discord import ui, Interaction, app_commands
import json
import os

# ================= CONFIG =================
TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "translations_data.json"

# ================= ВСЕ ФЛАГИ =================
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

# ================= DATA LOAD/SAVE =================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"news": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data_store = load_data()

# ================= BOT SETUP =================
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ================= КНОПКИ ПЕРЕВОДА =================
class PersonalTranslateView(ui.View):
    def __init__(self, message_id: str):
        super().__init__(timeout=3600)
        self.message_id = str(message_id)
        self._add_buttons()

    def _add_buttons(self):
        if self.message_id not in data_store["news"]:
            return
        languages = data_store["news"][self.message_id]
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
            if msg_id not in data_store["news"]:
                await interaction.response.send_message("❌ News not found.", ephemeral=True)
                return
            text = data_store["news"][msg_id].get(lang_code)
            if not text:
                await interaction.response.send_message(f"❌ No text in {lang_code}.", ephemeral=True)
                return
            await interaction.response.send_message(text, ephemeral=True)
        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

# ================= COMMAND: /news =================
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
    # Откладываем ответ (даёт до 15 минут на обработку)
    await interaction.response.defer(ephemeral=True)

    formatted_text = en_text.replace("\\n", "\n")
    message = await interaction.channel.send(formatted_text)
    msg_id = str(message.id)

    data_store["news"][msg_id] = {"en": en_text.replace("\\n", "\n")}
    if ru_text:
        data_store["news"][msg_id]["ru"] = ru_text.replace("\\n", "\n")
    if es_text:
        data_store["news"][msg_id]["es"] = es_text.replace("\\n", "\n")
    if fr_text:
        data_store["news"][msg_id]["fr"] = fr_text.replace("\\n", "\n")
    if de_text:
        data_store["news"][msg_id]["de"] = de_text.replace("\\n", "\n")

    save_data(data_store)
    view = PersonalTranslateView(msg_id)
    await message.edit(view=view)

    # Отправляем финальный ответ
    await interaction.followup.send(
        "✅ News published. Use buttons below for translations.",
        ephemeral=True
    )

# ================= COMMAND: /lang_add =================
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
    await interaction.response.defer(ephemeral=True)

    if message_id not in data_store["news"]:
        await interaction.followup.send("❌ News post not found.", ephemeral=True)
        return

    data_store["news"][message_id][lang_code] = text.replace("\\n", "\n")
    save_data(data_store)

    try:
        channel = interaction.channel
        msg = await channel.fetch_message(int(message_id))
        view = PersonalTranslateView(message_id)
        await msg.edit(view=view)
    except Exception as e:
        print(f"Failed to update buttons: {e}")

    await interaction.followup.send(
        f"✅ Added {get_flag(lang_code)} `{lang_code}` to news {message_id}",
        ephemeral=True
    )

# ================= COMMAND: /lang_remove =================
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
    await interaction.response.defer(ephemeral=True)

    if message_id not in data_store["news"]:
        await interaction.followup.send("❌ News post not found.", ephemeral=True)
        return
    if lang_code not in data_store["news"][message_id]:
        await interaction.followup.send(f"❌ Language `{lang_code}` not found.", ephemeral=True)
        return
    if lang_code == "en" and len(data_store["news"][message_id]) == 1:
        await interaction.followup.send("❌ Cannot remove the only language (English).", ephemeral=True)
        return

    del data_store["news"][message_id][lang_code]
    save_data(data_store)

    try:
        channel = interaction.channel
        msg = await channel.fetch_message(int(message_id))
        view = PersonalTranslateView(message_id)
        await msg.edit(view=view)
    except Exception as e:
        print(f"Failed to update buttons: {e}")

    await interaction.followup.send(
        f"✅ Removed language `{lang_code}` from news {message_id}",
        ephemeral=True
    )

# ================= COMMAND: /lang_list =================
@tree.command(name="lang_list", description="Show all languages for a news post")
@app_commands.describe(message_id="ID of the news message")
async def lang_list(
    interaction: Interaction,
    message_id: str
):
    await interaction.response.defer(ephemeral=True)

    if message_id not in data_store["news"]:
        await interaction.followup.send("❌ News post not found.", ephemeral=True)
        return

    langs = data_store["news"][message_id]
    embed = discord.Embed(
        title=f"📚 Languages for news {message_id}",
        description="\n".join([f"• {get_flag(k)} **{k.upper()}**: {v[:50]}..." for k, v in langs.items()]),
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# ================= COMMAND: /help =================
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

# ================= BOT STARTUP =================
@bot.event
async def on_ready():
    await tree.sync()
    await bot.change_presence(status=discord.Status.online)
    print(f"✅ Bot online as {bot.user}")
    print("📰 /news — Publish (English priority)")
    print("➕ /lang_add — Add language")
    print("➖ /lang_remove — Remove language")
    print("📋 /lang_list — List languages")
    print("❓ /help — Show all commands")
    print(f"💾 Data stored in {DATA_FILE}")

bot.run(TOKEN)

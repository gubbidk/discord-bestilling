import os
import json
import time
import discord
from discord.ext import commands
from datetime import datetime

# =====================
# KONFIG
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN mangler")

BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))
if BESTIL_CHANNEL_ID == 0:
    raise RuntimeError("BESTIL_CHANNEL_ID mangler")

SESSIONS_FILE = "sessions.json"
PRICES_FILE = "prices.json"

# =====================
# DISCORD SETUP
# =====================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# DATA
# =====================
def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        return {"current": None, "sessions": {}}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_sessions(data):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_prices():
    if not os.path.exists(PRICES_FILE):
        return {}
    with open(PRICES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

PRICES = load_prices()

def calc_total(items):
    return sum(items[i] * PRICES.get(i, 0) for i in items)

# =====================
# EVENTS
# =====================
@bot.event
async def on_ready():
    print(f"✅ Bot online som {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id != BESTIL_CHANNEL_ID:
        return

    content = message.content.strip().lower()
    if not content:
        return

    user = str(message.author)

    sessions = load_sessions()
    current = sessions.get("current")

    # =====================
    # 📦 LAGER
    # =====================
    if content == "lager":
        text = "📦 **Lager / Priser**\n"
        for item, price in PRICES.items():
            text += f"• {item} – {price:,} kr\n"

        await message.channel.send(text, delete_after=15)
        try:
            await message.delete()
        except:
            pass
        return

    # =====================
    # INGEN AKTIV BESTILLING
    # =====================
    if not current:
        await message.channel.send(
            f"🔴 {message.author.mention} der er ingen aktiv bestilling",
            delete_after=6
        )
        return

    session = sessions["sessions"].get(current)
    if not session or not session.get("open"):
        await message.channel.send(
            f"🔒 {message.author.mention} bestillingen er lukket",
            delete_after=6
        )
        return

    orders = session["orders"]

    order = next((o for o in orders if o["user"] == user), None)
    if not order:
        order = {
            "id": str(time.time()),
            "user": user,
            "items": {k: 0 for k in PRICES},
            "total": 0,
            "time": datetime.now().strftime("%d-%m-%Y %H:%M")
        }
        orders.append(order)

    # =====================
    # PARSE "2 veste" / "veste"
    # =====================
    parts = content.split()
    amount = 1
    item = None

    if len(parts) == 1:
        item = parts[0]
    elif len(parts) >= 2 and parts[0].isdigit():
        amount = int(parts[0])
        item = parts[1]

    if item not in PRICES:
        await message.channel.send(
            f"❌ Ukendt vare: `{item}`",
            delete_after=5
        )
        return

    order["items"][item] += amount
    order["total"] = calc_total(order["items"])

    save_sessions(sessions)

    await message.channel.send(
        f"✅ {message.author.mention} **+{amount} {item}** "
        f"(Total: {order['total']:,} kr)",
        delete_after=6
    )

    try:
        await message.delete()
    except:
        pass

# =====================
# START
# =====================
bot.run(DISCORD_TOKEN)

import os
import json
import time
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

# =====================
# ENV / KONFIG
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN mangler")

BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))
if BESTIL_CHANNEL_ID == 0:
    raise RuntimeError("BESTIL_CHANNEL_ID mangler")

# =====================
# DATA DIRECTORY (PERSISTENT)
# =====================
DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)

SESSIONS_FILE = f"{DATA_DIR}/sessions.json"
LAGER_FILE    = f"{DATA_DIR}/lager.json"
PRICES_FILE   = f"{DATA_DIR}/prices.json"


# =====================
# LOAD DATA
# =====================
def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f)
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_sessions():
    return load_json(SESSIONS_FILE, {"current": None, "sessions": {}})

def save_sessions(data):
    save_json(SESSIONS_FILE, data)


def load_lager():
    return load_json(LAGER_FILE, {})

def load_prices():
    return load_json(PRICES_FILE, {})

def get_active_session_orders():
    data = load_sessions()
    current = data.get("current")
    if not current:
        return []
    return data.get("sessions", {}).get(current, {}).get("orders", [])

def calculate_remaining_lager():
    lager = load_lager()
    orders = get_active_session_orders()

    used = {item: 0 for item in lager}

    for o in orders:
        for item, amount in o.get("items", {}).items():
            if item in used:
                used[item] += amount

    remaining = {}
    for item, max_amount in lager.items():
        remaining[item] = max(0, max_amount - used.get(item, 0))

    return remaining

  
# =====================
# DISCORD SETUP
# =====================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# EVENTS
# =====================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot logged in as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id != BESTIL_CHANNEL_ID:
        return

    content = message.content.strip().lower()
    if not content:
        return

    # 🔄 Load data live
    lager = load_lager()
    prices = load_prices()
    user = str(message.author)

    # =====================
    # 📦 LAGER KOMMANDO
    # =====================
    if content == "lager":
        remaining = calculate_remaining_lager()

        if not remaining:
            await message.channel.send(
                "📦 **Lagerstatus**\n_(Ingen varer i lageret endnu)_",
                delete_after=5
            )
            return

        lines = ["📦 **Lagerstatus (tilbage)**"]
        for item, amount in remaining.items():
            status = "⚠️" if amount <= 5 else "✅"
            lines.append(f"{status} **{item}**: {amount}")

        await message.channel.send("\n".join(lines), delete_after=5)
        try:
            await message.delete()
        except discord.NotFound:
            pass
        return



    # =====================
    # 🧾 BESTILLING
    # =====================
    data = load_sessions()
    current = data.get("current")

    if not current:
        await message.channel.send(
            f"🔴 {message.author.mention} der er ingen aktiv bestilling",
            delete_after=6
        )
        return

    session = data["sessions"].setdefault(
        current,
        {"open": True, "orders": []}
    )

    if not session.get("open", False):
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
            "user_id": str(message.author.id),  # ✅ Discord ID
            "items": {k: 0 for k in prices},     # ✅ FIX HER
            "total": 0,
            "time": datetime.now().strftime("%d-%m-%Y %H:%M")
        }
        orders.append(order)

    # parsing: "2 cola" / "cola"
    parts = content.split()
    amount = 1
    item = None

    if len(parts) == 1:
        item = parts[0]
    elif len(parts) >= 2 and parts[0].isdigit():
        amount = int(parts[0])
        item = parts[1]

    remaining = calculate_remaining_lager()

    if item not in prices:
        await message.channel.send(
            f"❌ Ukendt vare: `{item}`",
            delete_after=6
        )
        return

    if remaining.get(item, 0) <= 0:
        await message.channel.send(
            f"⛔ **{item}** er udsolgt",
            delete_after=6
        )
        return

    if amount > remaining.get(item, 0):
        await message.channel.send(
            f"⚠️ Kun **{remaining.get(item, 0)} {item}** tilbage på lager",
            delete_after=6
        )
        return


    order["items"][item] += amount

    # genberegn total
    total = 0
    for i, a in order["items"].items():
        total += a * prices.get(i, 0)
    order["total"] = total

    save_sessions(data)

    await message.channel.send(
        f"✅ {message.author.mention} **{amount} {item} tilføjet** "
        f"(Total: {order['total']:,} kr)",
        delete_after=3
    )

    try:
        await message.delete()
    except discord.NotFound:
        pass

# =====================
# SLASH COMMAND
# =====================
@bot.tree.command(
    name="bestilling",
    description="Se din nuværende bestilling"
)
async def bestilling(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    data = load_sessions()
    current = data.get("current")

    if not current:
        await interaction.followup.send(
            "🔴 Der er ingen aktiv bestilling",
            ephemeral=True
        )
        return

    session = data["sessions"].get(current, {})
    orders = session.get("orders", [])
    user = str(interaction.user)

    order = next((o for o in orders if o.get("user") == user), None)

    if not order:
        await interaction.followup.send(
            "❌ Du har ikke lagt en bestilling endnu",
            ephemeral=True
        )
        return

    lines = []
    for item, amount in order.get("items", {}).items():
        if amount > 0:
            lines.append(f"• **{item}**: {amount}")

    if not lines:
        lines.append("_Ingen items_")

    text = (
        f"📦 **Din bestilling ({current})**\n\n"
        + "\n".join(lines)
        + f"\n\n💰 **Total:** {order.get('total', 0):,} kr"
    )

    await interaction.followup.send(text, ephemeral=True)

# =====================
# START
# =====================
bot.run(DISCORD_TOKEN)

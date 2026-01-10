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
BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))
DATA_DIR = os.getenv("DATA_DIR", "/data")

SESSIONS_FILE = f"{DATA_DIR}/sessions.json"
LAGER_FILE    = f"{DATA_DIR}/lager.json"
PRICES_FILE   = f"{DATA_DIR}/prices.json"

os.makedirs(DATA_DIR, exist_ok=True)

# =====================
# JSON HELPERS
# =====================
def load_json(path, default):
    if not os.path.exists(path):
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

# =====================
# LAGER (KUN AKTIV SESSION)
# =====================
def remaining_lager():
    data = load_sessions()
    current = data.get("current")
    if not current:
        return {}

    orders = data["sessions"][current]["orders"]
    lager = load_lager()

    used = {i: 0 for i in lager}
    for o in orders:
        for item, amount in o.get("items", {}).items():
            if item in used:
                used[item] += amount

    return {i: max(0, lager[i] - used[i]) for i in lager}

# =====================
# DISCORD BOT
# =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != BESTIL_CHANNEL_ID:
        return

    content = message.content.lower().strip()
    if not content:
        return

    data = load_sessions()
    prices = load_prices()

    # ===== LAGER KOMMANDO =====
    if content == "lager":
        remaining = remaining_lager()
        if not remaining:
            await message.channel.send("📦 Ingen aktiv bestilling", delete_after=5)
            return

        lines = ["📦 **Lagerstatus**"]
        for item, amount in remaining.items():
            lines.append(f"• **{item}**: {amount}")
        await message.channel.send("\n".join(lines), delete_after=5)
        return

    # ===== AKTIV SESSION =====
    current = data.get("current")
    if not current:
        await message.channel.send("🔴 Ingen aktiv bestilling", delete_after=5)
        return

    session_data = data["sessions"][current]
    if not session_data.get("open"):
        await message.channel.send("🔒 Bestillingen er lukket", delete_after=5)
        return

    orders = session_data["orders"]
    user = str(message.author)

    order = next((o for o in orders if o["user"] == user), None)
    if not order:
        order = {
            "id": str(time.time()),
            "user": user,
            "user_id": str(message.author.id),
            "items": {k: 0 for k in prices},
            "total": 0,
            "time": datetime.now().strftime("%d-%m-%Y %H:%M")
        }
        orders.append(order)

    # ===== PARSE INPUT =====
    parts = content.split()

    if len(parts) == 1:
        amount = 1
        item = parts[0]
    elif len(parts) >= 2 and parts[0].isdigit():
        amount = int(parts[0])
        item = parts[1]
    else:
        await message.channel.send("❌ Ugyldigt format", delete_after=5)
        return

    remaining = remaining_lager()

    if item not in prices:
        await message.channel.send(f"❌ Ukendt vare: {item}", delete_after=5)
        return

    if amount > remaining.get(item, 0):
        await message.channel.send(
            f"⚠️ Kun {remaining.get(item, 0)} {item} tilbage på lager",
            delete_after=5
        )
        return

    # 🔁 SÆT mængde (IKKE læg til)
    order["items"][item] = amount

    # genberegn total
    order["total"] = sum(
        order["items"][i] * prices[i] for i in order["items"]
    )

    save_sessions(data)

    await message.channel.send(
        f"✅ **{item} sat til {amount} stk** (Total {order['total']:,} kr)",
        delete_after=3
    )

# =====================
# START
# =====================
bot.run(DISCORD_TOKEN)

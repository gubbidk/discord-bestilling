import os
import json
import time
import discord
from discord.ext import commands
from datetime import datetime
from db import init_db
init_db()

# =====================
# KONFIG
# =====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))
DATA_DIR = os.getenv("DATA_DIR", "/data")

SESSIONS_FILE = f"{DATA_DIR}/sessions.json"
LAGER_FILE    = f"{DATA_DIR}/lager.json"
PRICES_FILE   = f"{DATA_DIR}/prices.json"
USER_STATS_FILE = f"{DATA_DIR}/user_stats.json"
DB_PATH = Path("/data/data.db")

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

def load_user_stats():
    return load_json(USER_STATS_FILE, {})

def save_user_stats(data):
    save_json(USER_STATS_FILE, data)

def is_user_locked(session_data, user_id):
    return user_id in session_data.get("locked_users", [])

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

    # =====================
    # ADMIN: LÅS / LÅS OP
    # =====================
    if (content.startswith("lås ") or content.startswith("låsop ")) and message.mentions:
        if not message.author.guild_permissions.administrator:
            await message.channel.send("⛔ Kun admins kan låse brugere", delete_after=5)
            return

        current = data.get("current")
        if not current:
            await message.channel.send("❌ Ingen aktiv bestilling", delete_after=5)
            return

        session_data = data["sessions"][current]
        session_data.setdefault("locked_users", [])

        target = message.mentions[0]
        uid = str(target.id)

        # 🔒 LÅS
        if content.startswith("lås "):
            if uid not in session_data["locked_users"]:
                session_data["locked_users"].append(uid)
                save_sessions(data)
                await message.channel.send(f"🔒 **{target} er nu låst**", delete_after=5)
            else:
                await message.channel.send("ℹ️ Brugeren er allerede låst", delete_after=5)
            return

        # 🔓 LÅS OP
        if content.startswith("låsop "):
            if uid in session_data["locked_users"]:
                session_data["locked_users"].remove(uid)
                save_sessions(data)
                await message.channel.send(f"🔓 **{target} er nu låst op**", delete_after=5)
            else:
                await message.channel.send("ℹ️ Brugeren er ikke låst", delete_after=5)
            return

    # =====================
    # LAGER KOMMANDO
    # =====================
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

    # =====================
    # AKTIV SESSION
    # =====================
    current = data.get("current")
    if not current:
        await message.channel.send("🔴 Ingen aktiv bestilling", delete_after=5)
        return

    session_data = data["sessions"][current]
    session_data.setdefault("locked_users", [])

    if not session_data.get("open"):
        await message.channel.send("🔒 Bestillingen er lukket", delete_after=5)
        return

    if is_user_locked(session_data, str(message.author.id)):
        await message.channel.send("🔒 Din bestilling er låst af en admin", delete_after=5)
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

    # =====================
    # PARSE INPUT
    # =====================
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

    # =====================
    # OPDATER ORDRE
    # =====================
    order["items"][item] = amount
    order["total"] = sum(order["items"][i] * prices[i] for i in order["items"])
    save_sessions(data)

    # =====================
    # PERSISTENT STATS (DELTA SAFE)
    # =====================
    stats = load_user_stats()
    uid = order["user_id"]
    order_id = order["id"]

    stats.setdefault(uid, {
        "total_spent": 0,
        "total_items": 0,
        "items": {},
        "orders": {}
    })

    previous = stats[uid]["orders"].get(order_id, {
        "total": 0,
        "items": {}
    })

    delta_total = order["total"] - previous.get("total", 0)
    stats[uid]["total_spent"] += delta_total

    for i, amount in order["items"].items():
        prev = previous["items"].get(i, 0)
        delta = amount - prev
        stats[uid]["total_items"] += delta
        stats[uid]["items"][i] = stats[uid]["items"].get(i, 0) + delta

    stats[uid]["orders"][order_id] = {
        "total": order["total"],
        "items": order["items"].copy()
    }

    save_user_stats(stats)

    await message.channel.send(
        f"✅ **{item} sat til {amount} stk** (Total {order['total']:,} kr)",
        delete_after=3
    )

# =====================
# START
# =====================
bot.run(DISCORD_TOKEN)

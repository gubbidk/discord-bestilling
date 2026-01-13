import os
import time
import discord
from discord.ext import commands
from datetime import datetime
from db import init_db, get_conn

init_db()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))

# =====================
# DB HELPERS
# =====================
def load_sessions():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM meta WHERE key='current'")
        row = c.fetchone()
        current = None if not row else eval(row[0])

        sessions = {}
        for name, open_, data in c.execute("SELECT name, open, data FROM sessions"):
            s = eval(data)
            s["open"] = bool(open_)
            s.setdefault("orders", [])
            s.setdefault("locked_users", [])
            sessions[name] = s

        return {"current": current, "sessions": sessions}

def save_sessions(data):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM sessions")
        for name, s in data["sessions"].items():
            c.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (name, int(s.get("open", False)), repr(s))
            )
        c.execute(
            "INSERT OR REPLACE INTO meta VALUES ('current', ?)",
            (repr(data.get("current")),)
        )
        conn.commit()

def load_prices():
    with get_conn() as conn:
        return dict(conn.execute("SELECT item, price FROM prices"))

def load_lager():
    with get_conn() as conn:
        return dict(conn.execute("SELECT item, amount FROM lager"))

def load_user_stats():
    with get_conn() as conn:
        return {uid: eval(data) for uid, data in conn.execute("SELECT user_id, data FROM user_stats")}

def save_user_stats(stats):
    with get_conn() as conn:
        c = conn.cursor()
        for uid, data in stats.items():
            c.execute(
                "INSERT OR REPLACE INTO user_stats VALUES (?, ?)",
                (uid, repr(data))
            )
        conn.commit()

# =====================
# LAGER (AKTIV SESSION)
# =====================
def remaining_lager():
    data = load_sessions()
    current = data["current"]
    if not current:
        return {}

    lager = load_lager()
    used = {k: 0 for k in lager}

    for o in data["sessions"][current]["orders"]:
        for item, amount in o["items"].items():
            used[item] += amount

    return {k: max(0, lager[k] - used[k]) for k in lager}

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
    # AKTIV SESSION
    # =====================
    current = data["current"]
    if not current:
        await message.channel.send("🔴 Ingen aktiv bestilling", delete_after=5)
        return

    session_data = data["sessions"][current]
    if not session_data["open"]:
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

    parts = content.split()
    amount = int(parts[0]) if len(parts) > 1 and parts[0].isdigit() else 1
    item = parts[-1]

    remaining = remaining_lager()
    if item not in prices:
        await message.channel.send("❌ Ukendt vare", delete_after=5)
        return

    if amount > remaining.get(item, 0):
        await message.channel.send("⚠️ Ikke nok på lager", delete_after=5)
        return

    order["items"][item] = amount
    order["total"] = sum(order["items"][i] * prices[i] for i in order["items"])
    save_sessions(data)

    # =====================
    # USER STATS
    # =====================
    stats = load_user_stats()
    uid = order["user_id"]

    stats.setdefault(uid, {
        "total_spent": 0,
        "total_items": 0,
        "items": {},
        "orders": {}
    })

    stats[uid]["total_spent"] += order["total"]
    stats[uid]["total_items"] += amount
    stats[uid]["items"][item] = stats[uid]["items"].get(item, 0) + amount
    stats[uid]["orders"][order["id"]] = order

    save_user_stats(stats)

    await message.channel.send(
        f"✅ **{item} sat til {amount} stk** ({order['total']} kr)",
        delete_after=3
    )

bot.run(DISCORD_TOKEN)

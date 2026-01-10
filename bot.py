import os
import json
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
    raise RuntimeError("BESTIL_CHANNEL_ID mangler eller er forkert")

SESSIONS_FILE = "sessions.json"
LAGER_FILE = "lager.json"

# =====================
# DISCORD SETUP
# =====================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# HJÆLPEFUNKTIONER
# =====================
def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        return {"current": None, "sessions": {}}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_sessions(data):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_lager():
    if not os.path.exists(LAGER_FILE):
        return {}
    with open(LAGER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def new_order(user, items):
    return {
        "id": str(datetime.now().timestamp()),
        "user": user,
        "items": items,
        "total": 0,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M")
    }

def calc_total(items):
    # Hvis du har prices.json kan du udvide her
    return sum(v for v in items.values())

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

    content = message.content.lower().strip()
    parts = content.split()

    sessions = load_sessions()
    current = sessions.get("current")

    if not current:
        return

    session = sessions["sessions"].get(current)
    if not session or not session.get("open"):
        return

    lager = load_lager()

    # -------- LAGER --------
    if content == "lager":
        lines = ["📦 **Lagerstatus**"]
        for item, max_amount in lager.items():
            used = sum(
                o["items"].get(item, 0)
                for o in session["orders"]
            )
            lines.append(f"{item}: {max_amount - used}")
        await message.channel.send("\n".join(lines), delete_after=10)
        try:
            await message.delete()
        except:
            pass
        return

    # -------- BESTIL ITEM --------
    if len(parts) != 2:
        return

    item, amount = parts
    if item not in lager or not amount.isdigit():
        return

    amount = int(amount)
    if amount <= 0:
        return

    used = sum(
        o["items"].get(item, 0)
        for o in session["orders"]
    )

    left = lager[item] - used
    if amount > left:
        await message.channel.send(
            f"❌ Kun {left} {item} tilbage",
            delete_after=5
        )
        try:
            await message.delete()
        except:
            pass
        return

    user_key = str(message.author)

    order = next(
        (o for o in session["orders"] if o["user"] == user_key),
        None
    )

    if not order:
        order = new_order(
            user_key,
            {i: 0 for i in lager}
        )
        session["orders"].append(order)

    order["items"][item] += amount
    order["total"] = calc_total(order["items"])

    save_sessions(sessions)

    try:
        await message.delete()
    except:
        pass

    await message.channel.send(
        f"✅ {message.author.mention} +{amount} {item}",
        delete_after=3
    )

    await bot.process_commands(message)

# =====================
# SLASH COMMAND
# =====================
@bot.tree.command(name="bestilling", description="Se din nuværende bestilling")
async def bestilling(interaction: discord.Interaction):
    sessions = load_sessions()
    current = sessions.get("current")

    if not current:
        await interaction.response.send_message(
            "🔴 Ingen aktiv bestilling",
            ephemeral=True
        )
        return

    orders = sessions["sessions"].get(current, {}).get("orders", [])
    user = str(interaction.user)

    order = next(
        (o for o in orders if o["user"] == user),
        None
    )

    if not order:
        await interaction.response.send_message(
            "❌ Du har ingen bestilling",
            ephemeral=True
        )
        return

    lines = [
        f"• {item}: {amount}"
        for item, amount in order["items"].items()
        if amount > 0
    ]

    text = (
        f"📦 **Din bestilling ({current})**\n\n"
        + ("\n".join(lines) if lines else "Ingen varer")
        + f"\n\n💰 **Total:** {order['total']:,} kr"
    )

    await interaction.response.send_message(
        text,
        ephemeral=True
    )

# =====================
# START
# =====================
bot.run(DISCORD_TOKEN)

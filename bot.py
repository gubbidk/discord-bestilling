import os
import discord
from discord.ext import commands
from data import load_sessions, save_sessions, new_order, calc_total
import json

TOKEN = os.getenv("DISCORD_TOKEN")
BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN mangler")

with open("lager.json") as f:
    LAGER = json.load(f)

with open("prices.json") as f:
    PRICES = json.load(f)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")

@bot.tree.command(name="bestilling", description="Se din bestilling")
async def bestilling(interaction: discord.Interaction):
    data = load_sessions()
    current = data.get("current")

    if not current:
        await interaction.response.send_message(
            "🔴 Der er ingen aktiv bestilling",
            ephemeral=True
        )
        return

    orders = data["sessions"][current]["orders"]
    user = str(interaction.user)

    order = next((o for o in orders if o["user"] == user), None)

    if not order:
        await interaction.response.send_message(
            "❌ Du har ingen bestilling",
            ephemeral=True
        )
        return

    lines = [
        f"• {i}: {a}"
        for i, a in order["items"].items()
        if a > 0
    ]

    text = (
        f"📦 **Din bestilling ({current})**\n\n"
        + "\n".join(lines)
        + f"\n\n💰 **Total:** {order['total']:,} kr"
    )

    await interaction.response.send_message(text, ephemeral=True)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != BESTIL_CHANNEL_ID:
        return

    content = message.content.lower().strip()
    parts = content.split()

    if len(parts) != 2:
        return

    item, amount = parts
    if item not in LAGER or not amount.isdigit():
        return

    amount = int(amount)

    data = load_sessions()
    current = data.get("current")

    if not current:
        return

    session = data["sessions"].setdefault(
        current, {"open": True, "orders": []}
    )

    orders = session["orders"]
    user_key = str(message.author)

    order = next((o for o in orders if o["user"] == user_key), None)
    if not order:
        order = new_order(user_key, {i: 0 for i in LAGER})
        orders.append(order)

    order["items"][item] = amount
    order["total"] = calc_total(order["items"], PRICES)

    save_sessions(data)

    try:
        await message.delete()
    except:
        pass

    await message.channel.send(
        f"✅ {message.author.mention} +{amount} {item}",
        delete_after=3
    )

bot.run(TOKEN)

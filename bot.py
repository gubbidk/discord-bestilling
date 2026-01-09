import discord
from discord.ext import commands
from discord import app_commands
from data import load, save, new_order, ensure_order_integrity

TOKEN = "MTQ1ODkzNDI1NTk4NjkzMzc2MQ.GAYGVa.q86yY9bB2PObfF0BdQi3yFqgBjW-ioH_cXd1WE"
BESTIL_CHANNEL_ID = 1458936290639876219

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot logged in as {bot.user}")

    channel = bot.get_channel(BESTIL_CHANNEL_ID)
    if channel:
        await channel.send("🟢 Bot startet")


# ---------- SLASH COMMAND ----------
@bot.tree.command(name="bestilling", description="Se din nuværende bestilling")
async def bestilling(interaction: discord.Interaction):
    sessions = load("sessions.json")
    session_name = sessions.get("current")

    if not session_name:
        await interaction.response.send_message(
            "🔴 Ingen aktiv bestilling",
            ephemeral=True
        )
        return

    session = sessions["sessions"].get(session_name)
    if not session:
        await interaction.response.send_message(
            "🔴 Ingen aktiv bestilling",
            ephemeral=True
        )
        return

    orders = session.get("orders", [])
    user = str(interaction.user)

    order = next((o for o in orders if o["user"] == user), None)
    if not order:
        await interaction.response.send_message(
            "❌ Du har ikke lagt en bestilling",
            ephemeral=True
        )
        return

    lines = [
        f"• {item}: {amount}"
        for item, amount in order["items"].items()
        if amount > 0
    ]

    text = (
        f"📦 **Din bestilling ({session_name})**\n\n"
        + "\n".join(lines)
        + f"\n\n💰 **Total:** {order['total']:,} kr"
    )

    await interaction.response.send_message(text, ephemeral=True)


# ---------- MESSAGE HANDLER ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != BESTIL_CHANNEL_ID:
        return

    sessions = load("sessions.json")

    # SIKKER STRUKTUR
    sessions.setdefault("sessions", {})
    sessions.setdefault("current", None)

    session_name = sessions["current"]
    if not session_name:
        await message.channel.send("🔴 Ingen aktiv bestilling", delete_after=5)
        await message.delete()
        return

    # SIKKER SESSION
    sessions["sessions"].setdefault(session_name, {
        "open": True,
        "orders": []
    })

    session = sessions["sessions"][session_name]
    orders = session["orders"]

    lager = load("lager.json")
    content = message.content.lower().strip()

    # ---------- LAGER ----------
    if content == "lager":
        lines = ["📦 **Lagerstatus**"]
        for item, max_amount in lager.items():
            used = sum(o["items"].get(item, 0) for o in orders)
            lines.append(f"{item}: {max_amount - used} tilbage")

        await message.channel.send("\n".join(lines), delete_after=10)
        await message.delete()
        return

    # ---------- PARSE INPUT ----------
    parts = content.split()
    if len(parts) != 2:
        return

    item, amount = parts
    if item not in lager or not amount.isdigit():
        return

    amount = int(amount)
    if amount <= 0:
        return

    used = sum(o["items"].get(item, 0) for o in orders)
    left = lager[item] - used

    if amount > left:
        await message.channel.send(
            f"❌ Kun {left} {item} tilbage",
            delete_after=5
        )
        await message.delete()
        return

    # ---------- FIND / OPRET ORDRE ----------
    user_key = str(message.author)
    order = next((o for o in orders if o["user"] == user_key), None)

    if not order:
        order = new_order(user_key, {i: 0 for i in lager})
        orders.append(order)

    # ---------- OPDATER ----------
    order["items"][item] = amount
    ensure_order_integrity(order)

    save("sessions.json", sessions)

    await message.delete()
    await message.channel.send(
        f"✅ {message.author.mention} satte {item} = {amount}",
        delete_after=3
    )


bot.run(TOKEN)

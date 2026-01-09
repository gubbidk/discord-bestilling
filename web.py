import threading
import os
import discord
from discord.ext import commands
from flash import Flask, render_template, request, redirect, session, jsonify
import json
import time


# =====================
# KONFIG
# =====================
DISCORD_TOKEN = os.getenv("discord")
BESTIL_CHANNEL_ID = int(os.getenv("BESTIL_CHANNEL_ID", "0"))
SESSION_FILE = "sessions.json"

ADMIN_KEY = "thomas"  
DISCORD_WEBHOOK = ""


# =====================
# FLASK
# =====================
app = Flask(__name__)
app.secret_key  = "fedko"

def load():
    if not os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "w") as f:
            json.dump({"current": None, "sessions": {}}, f)
        with open(SESSIONN_FILE, "r") as f:
            return json.load(f)
            
def save(data):
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=2)

# =====================
# HJÆLPERE
# =====================
def is_admin():
    return flask_session.get("admin", False)


def send_discord(msg):
    if DISCORD_WEBHOOK.startswith("http"):
        requests.post(DISCORD_WEBHOOK, json={"content": msg})


def normalize(data):
    """
    Sikrer format:
    sessions[name] = { open: bool, orders: [...] }
    """
    if "sessions" not in data:
        data["sessions"] = {}

    for name, val in data["sessions"].items():
        if isinstance(val, list):
            data["sessions"][name] = {
                "open": False,
                "orders": val
            }
        else:
            data["sessions"][name].setdefault("open", False)
            data["sessions"][name].setdefault("orders", [])

    return data

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    data = normalize(load(SESSIONS_FILE))
    return render_template(
        "index.html",
        sessions=list(data["sessions"].keys()),
        current=data.get("current"),
        is_admin=session.get("admin", False)
    )


@app.route("/admin")
def admin_login():
    if request.args.get("key") != ADMIN_KEY:
        return "❌ Forkert admin-nøgle", 403

    flask_session["admin"] = True
    return redirect("/")


@app.route("/open_session")
def open_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))

    if data.get("current"):
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": []}
    data["current"] = name

    save(SESSIONS_FILE, data)
    send_discord(f"🟢 **{name} åbnet**")

    return redirect("/")


@app.route("/close_session")
def close_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))
    if data.get("current"):
        send_discord(f"🔴 **{data['current']} lukket**")
        data["sessions"][data["current"]]["open"] = False
        data["current"] = None
        save(SESSIONS_FILE, data)

    return redirect("/")


@app.route("/delete_session/<name>")
def delete_session(name):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))

    if name in data["sessions"]:
        del data["sessions"][name]
        if data.get("current") == name:
            data["current"] = None
        save(SESSIONS_FILE, data)
        send_discord(f"🗑️ **{name} slettet**")

    return redirect("/")


@app.route("/session/<name>")
def session_view(name):
    data = normalize(load(SESSIONS_FILE))

    if name not in data["sessions"]:
        return "Findes ikke", 404

    orders = data["sessions"][name]["orders"]
    total = sum(o.get("total", 0) for o in orders)

    return render_template(
        "session.html",
        name=name,
        orders=orders,
        total=total,
        admin=is_admin()
    )


@app.route("/edit_order/<name>/<order_id>", methods=["GET", "POST"])
def edit_order(name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))
    orders = data["sessions"][name]["orders"]
    order = next((o for o in orders if o["id"] == order_id), None)

    if not order:
        return "Ordre findes ikke", 404

    if request.method == "POST":
        for item in order["items"]:
            order["items"][item] = int(request.form.get(item, 0))
        order["total"] = calc_total(order["items"])

        save(SESSIONS_FILE, data)
        send_discord(
            f"✏️ **Ordre opdateret** ({order['user']})\n"
            f"💰 Ny total: {order['total']:,} kr"
        )
        return redirect(f"/session/{name}")

    return render_template(
        "edit_order.html",
        order=order,
        session=name,
        prices=PRICES,
        admin=True
    )


@app.route("/delete_order/<name>/<order_id>")
def delete_order(name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))
    orders = data["sessions"][name]["orders"]

    order = next((o for o in orders if o["id"] == order_id), None)
    data["sessions"][name]["orders"] = [
        o for o in orders if o["id"] != order_id
    ]

    save(SESSIONS_FILE, data)

    if order:
        items = "\n".join(
            f"- {k}: {v}"
            for k, v in order["items"].items() if v > 0
        )
        send_discord(
            f"🗑️ **Ordre slettet** ({order['user']})\n{items}"
        )

    return redirect(f"/session/{name}")


@app.route("/session_data/<name>")
def session_data(name):
    data = normalize(load(SESSIONS_FILE))
    orders = data["sessions"].get(name, {}).get("orders", [])

    payload = json.dumps(orders, sort_keys=True)
    return jsonify({
        "hash": hashlib.md5(payload.encode()).hexdigest()
    })
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
    if message.author.bot:
        return
    if message.channel.id != BESTIL_CHANNEL_ID:
        return

    data = load()
    session_name = data.get("current")

    if not session_name:
        await message.channel.send("❌ Ingen aktiv bestilling", delete_after=5)
        return

    orders = data["sessions"][session_name]["orders"]
    user = str(message.author)

    order = next((o for o in orders if o["user"] == user), None)
    if not order:
        order = {"user": user, "items": {}, "total": 0}
        orders.append(order)

    order["items"][message.content] = order["items"].get(message.content, 0) + 1
    order["total"] = sum(order["items"].values())

    save(data)
    await message.delete()
# =====================
# start lortet
# =====================
def run_bot():
    bot.run(DISCORD_TOKEN)
    
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)

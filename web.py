import os
import json
import hashlib
from flask import Flask, render_template, request, redirect, session, jsonify
import requests
from urllib.parse import urlencode

# =====================
# KONFIGURATION
# =====================
SESSIONS_FILE = "sessions.json"
ADMIN_KEY = os.getenv("ADMIN_KEY", "thomas")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_ADMIN_ROLE = os.getenv("DISCORD_ADMIN_ROLE")

ACCESS_FILE = "access.json"
OAUTH_REDIRECT = "/auth/callback"

# =====================
# FLASK SETUP
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-123")

# =====================
# FIL-HJÆLPERE
# =====================
def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"current": None, "sessions": {}}, f)

    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sessions(data):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize(data):
    data.setdefault("current", None)
    data.setdefault("sessions", {})

    for name, val in data["sessions"].items():
        if isinstance(val, list):
            data["sessions"][name] = {
                "open": False,
                "orders": val
            }
        else:
            val.setdefault("open", False)
            val.setdefault("orders", [])

    return data

def load_access():
    if not os.path.exists(ACCESS_FILE):
        return {"blocked": []}
    with open(ACCESS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_access(data):
    with open(ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def is_blocked(discord_id):
    return discord_id in load_access().get("blocked", [])


def is_admin():
    return session.get("admin", False)

@app.route("/login")
def login():
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": request.url_root.strip("/") + OAUTH_REDIRECT,
        "response_type": "code",
        "scope": "identify guilds.members.read"
    }

    return redirect(
        "https://discord.com/api/oauth2/authorize?" + urlencode(params)
    )

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    if "user" not in session:
    return redirect("/login")
    data = normalize(load_sessions())
    return render_template(
        "index.html",
        sessions=list(data["sessions"].keys()),
        current=data["current"],
        admin=is_admin()
    )

@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return "No code", 400

    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": request.url_root.strip("/") + OAUTH_REDIRECT
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    ).json()

    token = token_res.get("access_token")
    if not token:
        return "OAuth failed", 403

    headers = {"Authorization": f"Bearer {token}"}

    user = requests.get(
        "https://discord.com/api/users/@me",
        headers=headers
    ).json()

    member = requests.get(
        f"https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member",
        headers=headers
    )

    if member.status_code != 200:
        return "Ikke medlem af serveren", 403

    if is_blocked(user["id"]):
        return "Du er blokeret fra web-panelet", 403

    roles = member.json().get("roles", [])

    is_admin = False
    guild_roles = requests.get(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
        headers={"Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}"}
    ).json()

    role_map = {r["id"]: r["name"] for r in guild_roles}

    for r in roles:
        if role_map.get(r) == DISCORD_ADMIN_ROLE:
            is_admin = True

    session["user"] = {
        "id": user["id"],
        "name": user["username"]
    }
    session["admin"] = is_admin

    return redirect("/")


@app.route("/admin")
def admin_login():
    if request.args.get("key") != ADMIN_KEY:
        return "❌ Forkert admin-nøgle", 403

    session["admin"] = True
    return redirect("/")


@app.route("/open_session")
def open_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())

    if data["current"]:
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": []}
    data["current"] = name

    save_sessions(data)
    return redirect("/")


@app.route("/close_session")
def close_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())

    if data["current"]:
        data["sessions"][data["current"]]["open"] = False
        data["current"] = None
        save_sessions(data)

    return redirect("/")


@app.route("/delete_session/<name>")
def delete_session(name):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())

    if name in data["sessions"]:
        del data["sessions"][name]
        if data["current"] == name:
            data["current"] = None

        save_sessions(data)

    return redirect("/")


@app.route("/session/<name>")
def view_session(name):
    data = normalize(load_sessions())

    if name not in data["sessions"]:
        return "Bestilling findes ikke", 404

    orders = data["sessions"][name]["orders"]
    total = sum(o.get("total", 0) for o in orders if isinstance(o, dict))

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

    data = normalize(load_sessions())
    orders = data["sessions"][name]["orders"]

    order = next((o for o in orders if o["id"] == order_id), None)
    if not order:
        return "Ordre findes ikke", 404

    if request.method == "POST":
        total = 0
        for item in order["items"]:
            amount = int(request.form.get(item, 0))
            order["items"][item] = max(0, amount)
            total += amount

        order["total"] = total
        save_sessions(data)
        return redirect(f"/session/{name}")

    return render_template(
        "edit_order.html",
        order=order,
        session=name,
        admin=True
    )


@app.route("/delete_order/<name>/<order_id>")
def delete_order(name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    orders = data["sessions"][name]["orders"]

    data["sessions"][name]["orders"] = [
        o for o in orders if o["id"] != order_id
    ]

    save_sessions(data)
    return redirect(f"/session/{name}")


@app.route("/session_data/<name>")
def session_data(name):
    data = normalize(load_sessions())
    orders = data["sessions"].get(name, {}).get("orders", [])

    payload = json.dumps(orders, sort_keys=True)
    return jsonify({
        "hash": hashlib.md5(payload.encode()).hexdigest()
    })

@app.route("/admin/block/<discord_id>")
def block_user(discord_id):
    if not session.get("admin"):
        return "Du er bannet fra web-panelet", 403

    data = load_access()
    if discord_id not in data["blocked"]:
        data["blocked"].append(discord_id)
        save_access(data)

    return redirect("/")

# =====================
# START
# =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

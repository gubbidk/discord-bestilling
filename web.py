import os
import json
import hashlib
from flask import Flask, render_template, request, redirect, session, jsonify
import requests
from urllib.parse import urlencode
from datetime import datetime

# =====================
# KONFIGURATION
# =====================
SESSIONS_FILE = "sessions.json"
ACCESS_FILE = "access.json"
AUDIT_FILE = "audit.json"

ADMIN_KEY = os.getenv("ADMIN_KEY", "thomas")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_ADMIN_ROLE = os.getenv("DISCORD_ADMIN_ROLE")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_USER_ROLE = os.getenv("DISCORD_USER_ROLE")
OAUTH_REDIRECT = "/auth/callback"

# =====================
# FLASK SETUP
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-123")

# =====================
# FIL-HJÆLPERE
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

def normalize(data):
    data.setdefault("current", None)
    data.setdefault("sessions", {})
    for s in data["sessions"].values():
        s.setdefault("open", False)
        s.setdefault("orders", [])
    return data

def load_access():
    return load_json(ACCESS_FILE, {"blocked": []})

def save_access(data):
    save_json(ACCESS_FILE, data)

def load_audit():
    return load_json(AUDIT_FILE, {"events": []})

def audit_log(action, admin, target):
    data = load_audit()
    data["events"].append({
        "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "action": action,
        "admin": admin,
        "target": target
    })
    save_json(AUDIT_FILE, data)

def is_admin():
    return session.get("admin", False)

def is_blocked(discord_id):
    return discord_id in load_access().get("blocked", [])

# =====================
# AUTH
# =====================
@app.route("/login")
def login():
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": request.url_root.strip("/") + OAUTH_REDIRECT,
        "response_type": "code",
        "scope": "identify guilds.members.read"
    }
    return redirect("https://discord.com/api/oauth2/authorize?" + urlencode(params))

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

    # Discord user
    user = requests.get(
        "https://discord.com/api/users/@me",
        headers=headers
    ).json()

    # Guild member
    member_res = requests.get(
        f"https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member",
        headers=headers
    )

    if member_res.status_code != 200:
        return "Du er ikke medlem af Discord-serveren", 403

    if is_blocked(user["id"]):
        return "Du er blokeret fra web-panelet", 403

    roles = member_res.json().get("roles", [])

    # Hent guild roles (kræver bot token)
    guild_roles = requests.get(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
        headers={
            "Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}"
        }
    ).json()

    role_map = {r["id"]: r["name"] for r in guild_roles}

    user_has_access = False
    admin = False

    for r in roles:
        role_name = role_map.get(r)
        if role_name == DISCORD_ADMIN_ROLE:
            admin = True
            user_has_access = True
        if role_name == DISCORD_USER_ROLE:
            user_has_access = True

    if not user_has_access:
        return "Du har ikke adgang til web-panelet", 403

    session["user"] = {
        "id": user["id"],
        "name": user["username"],
        "avatar": user.get("avatar")
    }
    session["admin"] = admin

    return redirect("/")

# =====================
# ROUTES
# =====================
@app.route("/edit_order/<session_name>/<order_id>", methods=["GET", "POST"])
def edit_order(session_name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())

    if session_name not in data["sessions"]:
        return "Bestilling findes ikke", 404

    orders = data["sessions"][session_name]["orders"]
    order = next((o for o in orders if o.get("id") == order_id), None)

    if not order:
        return "Ordre findes ikke", 404

    prices = load_json("prices.json", {})

    if request.method == "POST":
        total = 0
        for item in order["items"]:
            amount = int(request.form.get(item, 0))
            order["items"][item] = max(0, amount)
            total += amount * prices.get(item, 0)

        order["total"] = total
        save_sessions(data)

        return redirect(f"/session/{session_name}")

    return render_template(
        "edit_order.html",
        order=order,
        session=session_name,
        prices=prices,
        admin=True
    )



@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")

    data = normalize(load_sessions())
    return render_template(
        "index.html",
        sessions=list(data["sessions"].keys()),
        current=data["current"],
        admin=is_admin(),
        user=session["user"]
    )

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

@app.route("/session/<name>")
def view_session(name):
    data = normalize(load_sessions())
    if name not in data["sessions"]:
        return "Findes ikke", 404

    orders = data["sessions"][name]["orders"]
    total = sum(o.get("total", 0) for o in orders)

    return render_template(
        "session.html",
        name=name,
        orders=orders,
        total=total,
        admin=is_admin(),
        user=session["user"]
    )

@app.route("/admin/block/<discord_id>")
def block_user(discord_id):
    if not is_admin():
        return "Forbidden", 403

    data = load_access()
    if discord_id not in data["blocked"]:
        data["blocked"].append(discord_id)
        save_access(data)
        audit_log("block", session["user"]["name"], discord_id)

    return redirect("/")

@app.route("/admin/unblock/<discord_id>")
def unblock_user(discord_id):
    if not is_admin():
        return "Forbidden", 403

    data = load_access()
    if discord_id in data["blocked"]:
        data["blocked"].remove(discord_id)
        save_access(data)
        audit_log("unblock", session["user"]["name"], discord_id)

    return redirect("/")

@app.route("/admin/audit")
def audit():
    if not is_admin():
        return "Forbidden", 403
    data = load_audit()
    return render_template("audit.html", events=reversed(data["events"]))

@app.route("/session_data/<name>")
def session_data(name):
    data = normalize(load_sessions())
    orders = data["sessions"].get(name, {}).get("orders", [])
    payload = json.dumps(orders, sort_keys=True)
    return jsonify({"hash": hashlib.md5(payload.encode()).hexdigest()})

@app.route("/toggle_session/<name>")
def toggle_session(name):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())

    if name not in data["sessions"]:
        return redirect("/")

    session = data["sessions"][name]
    session["open"] = not session.get("open", False)

    if not session["open"] and data.get("current") == name:
        data["current"] = None
    elif session["open"]:
        data["current"] = name

    save_sessions(data)
    return redirect("/")

# =====================
# START
# =====================
if __name__ == "__main__":
    app.run(debug=True)

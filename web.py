import os
import json
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO

# =====================
# KONFIGURATION
# =====================
DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)

SESSIONS_FILE = f"{DATA_DIR}/sessions.json"
ACCESS_FILE   = f"{DATA_DIR}/access.json"
AUDIT_FILE    = f"{DATA_DIR}/audit.json"
LAGER_FILE    = f"{DATA_DIR}/lager.json"
PRICES_FILE   = f"{DATA_DIR}/prices.json"

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_ADMIN_ROLE = os.getenv("DISCORD_ADMIN_ROLE")
DISCORD_USER_ROLE = os.getenv("DISCORD_USER_ROLE")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_TOKEN")

OAUTH_REDIRECT = "/auth/callback"

# =====================
# FLASK SETUP
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")

socketio = SocketIO(app, cors_allowed_origins="*")

# =====================
# HJÆLPERE
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
    socketio.emit("update")

def normalize(data):
    data.setdefault("current", None)
    data.setdefault("sessions", {})
    for s in data["sessions"].values():
        s.setdefault("open", False)
        s.setdefault("orders", [])
    return data

def load_access():
    data = load_json(ACCESS_FILE, {"blocked": [], "users": {}})
    data.setdefault("blocked", [])
    data.setdefault("users", {})
    return data

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

def load_lager():
    return load_json(LAGER_FILE, {})

def load_prices():
    return load_json(PRICES_FILE, {})

def get_active_session_orders():
    data = normalize(load_sessions())
    current = data.get("current")
    if not current:
        return []
    return data["sessions"].get(current, {}).get("orders", [])

def get_lager_status(session_orders):
    lager = load_lager()
    used = {}

    for o in session_orders:
        for item, amount in o.get("items", {}).items():
            used[item] = used.get(item, 0) + amount

    status = {}
    for item, max_amount in lager.items():
        left = max_amount - used.get(item, 0)
        pct = 0 if max_amount == 0 else left / max_amount

        if left <= 0:
            level = "danger"
        elif pct < 0.3:
            level = "warning"
        else:
            level = "ok"

        status[item] = {
            "left": left,
            "max": max_amount,
            "level": level
        }

    return status

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

    token = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": request.url_root.strip("/") + OAUTH_REDIRECT
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    ).json().get("access_token")

    if not token:
        return "OAuth failed", 403

    headers = {"Authorization": f"Bearer {token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers).json()

    member = requests.get(
        f"https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member",
        headers=headers
    )

    if member.status_code != 200:
        return "Ikke medlem af Discord-serveren", 403

    if is_blocked(user["id"]):
        return "Du er blokeret fra web-panelet", 403

    roles = member.json().get("roles", [])
    guild_roles = requests.get(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    ).json()

    role_map = {r["id"]: r["name"] for r in guild_roles}

    admin = False
    access_ok = False

    for r in roles:
        name = role_map.get(r)
        if name == DISCORD_ADMIN_ROLE:
            admin = True
            access_ok = True
        if name == DISCORD_USER_ROLE:
            access_ok = True

    if not access_ok:
        return "Ingen adgang", 403

    session["user"] = {
        "id": user["id"],
        "name": user["username"],
        "avatar": user.get("avatar")
    }
    session["admin"] = admin

    access = load_access()
    uid = user["id"]

    access["users"][uid] = {
        "name": user["username"],
        "first_seen": access["users"].get(uid, {}).get(
            "first_seen",
            datetime.now().strftime("%d-%m-%Y %H:%M")
        ),
        "last_seen": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "role": "admin" if admin else "user"
    }
    save_access(access)

    return redirect("/")

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")

    data = normalize(load_sessions())
    totals = {
        name: sum(o.get("total", 0) for o in s.get("orders", []))
        for name, s in data["sessions"].items()
    }

    return render_template(
        "index.html",
        sessions=data["sessions"],
        totals=totals,
        current=data["current"],
        admin=is_admin(),
        user=session["user"]
    )

@app.route("/session/<name>")
def view_session(name):
    if "user" not in session:
        return redirect("/login")

    data = normalize(load_sessions())
    if name not in data["sessions"]:
        return "Findes ikke", 404

    orders = data["sessions"][name]["orders"]
    active_orders = get_active_session_orders()
    lager_status = get_lager_status(active_orders)
    total = sum(o.get("total", 0) for o in orders)

    return render_template(
        "session.html",
        name=name,
        orders=orders,
        total=total,
        lager_status=lager_status,
        admin=is_admin(),
        user=session["user"]
    )

@app.route("/open_session")
def open_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())

    if data.get("current"):
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": []}
    data["current"] = name

    save_sessions(data)
    audit_log("open_session", session["user"]["name"], name)

    return redirect("/")

@app.route("/close_session")
def close_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    if not data.get("current"):
        return redirect("/")

    name = data["current"]
    data["sessions"][name]["open"] = False
    data["current"] = None

    save_sessions(data)
    audit_log("close_session", session["user"]["name"], name)

    return redirect("/")

@app.route("/delete_session/<name>")
def delete_session(name):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    if name not in data["sessions"]:
        return "Not found", 404

    if data.get("current") == name:
        data["current"] = None

    del data["sessions"][name]
    save_sessions(data)
    audit_log("delete_session", session["user"]["name"], name)

    return redirect("/")

@app.route("/admin/users")
def admin_users():
    if not is_admin():
        return "Forbidden", 403

    access = load_access()

    # Sortér: admins først, derefter users, derefter navn
    users = dict(
        sorted(
            access.get("users", {}).items(),
            key=lambda x: (
                0 if x[1].get("role") == "admin" else 1,
                x[1].get("name", "").lower()
            )
        )
    )

    return render_template(
        "admin_users.html",
        users=users,
        blocked=access.get("blocked", []),
        user=session["user"],
        admin=True
    )


@app.route("/admin/block/<discord_id>")
def block_user(discord_id):
    if not is_admin():
        return "Forbidden", 403

    access = load_access()
    if discord_id not in access["blocked"]:
        access["blocked"].append(discord_id)
        save_access(access)
        audit_log("block", session["user"]["name"], discord_id)

    if session.get("user", {}).get("id") == discord_id:
        session.clear()

    return redirect("/admin/users")

@app.route("/admin/unblock/<discord_id>")
def unblock_user(discord_id):
    if not is_admin():
        return "Forbidden", 403

    access = load_access()
    if discord_id in access["blocked"]:
        access["blocked"].remove(discord_id)
        save_access(access)
        audit_log("unblock", session["user"]["name"], discord_id)

    return redirect("/admin/users")

@app.route("/admin/audit")
def audit():
    if not is_admin():
        return "Forbidden", 403

    events = list(reversed(load_audit()["events"]))
    action = request.args.get("action")
    if action:
        events = [e for e in events if e["action"] == action]

    return render_template("audit.html", events=events)

# =====================
# START
# =====================
if __name__ == "__main__":
    socketio.run(app, debug=True)

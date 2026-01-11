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

# =====================
# DATA LOADERS
# =====================
def load_sessions():
    data = load_json(SESSIONS_FILE, {"current": None, "sessions": {}})
    data.setdefault("current", None)
    data.setdefault("sessions", {})
    for s in data["sessions"].values():
        s.setdefault("open", False)
        s.setdefault("orders", [])
        s.setdefault("locked_users", [])
    return data

def save_sessions(data):
    save_json(SESSIONS_FILE, data)
    socketio.emit("update")

def load_access():
    data = load_json(ACCESS_FILE, {"blocked": [], "users": {}})
    data.setdefault("blocked", [])
    data.setdefault("users", {})
    return data

def save_access(data):
    save_json(ACCESS_FILE, data)

def load_lager():
    return load_json(LAGER_FILE, {})

def load_prices():
    return load_json(PRICES_FILE, {})

def load_audit():
    return load_json(AUDIT_FILE, {"events": []})

# =====================
# HELPERS
# =====================
def is_admin():
    return session.get("admin", False)

def is_blocked(uid):
    return uid in load_access()["blocked"]

def audit_log(action, admin, target):
    data = load_audit()
    data["events"].append({
        "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "action": action,
        "admin": admin,
        "target": target
    })
    save_json(AUDIT_FILE, data)

# =====================
# LAGER STATUS (PR SESSION)
# =====================
def get_lager_status_for_session(session_name):
    data = load_sessions()
    session_data = data["sessions"].get(session_name)
    if not session_data:
        return {}

    orders = session_data["orders"]
    lager = load_lager()

    used = {item: 0 for item in lager}
    for o in orders:
        for item, amount in o.get("items", {}).items():
            used[item] += amount

    status = {}
    for item, max_amount in lager.items():
        left = max(0, max_amount - used[item])
        pct = 0 if max_amount == 0 else left / max_amount
        level = "danger" if left <= 0 else "warning" if pct < 0.3 else "ok"

        status[item] = {
            "left": left,
            "max": max_amount,
            "level": level
        }

    return status

# =====================
# BLOCK ENFORCEMENT
# =====================
@app.before_request
def enforce_blocked_users():
    if "user" not in session:
        return
    uid = session["user"].get("id")
    if uid and is_blocked(uid):
        session.clear()
        return redirect("/login")

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
        return "Ikke medlem af serveren", 403

    if is_blocked(user["id"]):
        return "Blokeret", 403

    roles = member.json().get("roles", [])
    resp = requests.get(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    )

    role_map = {r["id"]: r["name"] for r in resp.json()}

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
    access["users"][user["id"]] = {
        "name": user["username"],
        "role": "admin" if admin else "user",
        "avatar": user.get("avatar"),
        "first_seen": access["users"].get(user["id"], {}).get(
            "first_seen", datetime.now().strftime("%d-%m-%Y %H:%M")
        ),
        "last_seen": datetime.now().strftime("%d-%m-%Y %H:%M")
    }
    save_access(access)

    return redirect("/")

# =====================
# ADMIN – USER HISTORY
# =====================
@app.route("/admin/user_history")
def user_history():
    if not is_admin():
        return "Forbidden", 403

    uid = request.args.get("uid")
    orders = []
    stats = {
        "total_spent": 0,
        "total_items": 0,
        "items": {}
    }
    grand_total = 0

    if uid:
        data = load_sessions()

        for sname, s in data["sessions"].items():
            for o in s["orders"]:
                if o.get("user_id") == uid:
                    orders.append({
                        "session": sname,
                        "items": o["items"],
                        "total": o["total"],
                        "time": o["time"]
                    })

                    stats["total_spent"] += o["total"]
                    grand_total += o["total"]

                    for item, amount in o["items"].items():
                        if amount > 0:
                            stats["total_items"] += amount
                            stats["items"][item] = stats["items"].get(item, 0) + amount

    most_bought = None
    filtered = {k: v for k, v in stats["items"].items() if k.lower() != "veste"}
    if filtered:
        most_bought = max(filtered.items(), key=lambda x: x[1])[0]

    access = load_access()
    user_info = access["users"].get(uid)

    locked_users = []
    data = load_sessions()
    if data.get("current"):
        locked_users = data["sessions"][data["current"]].get("locked_users", [])

    return render_template(
        "user_history.html",
        uid=uid,
        orders=orders,
        stats=stats,
        most_bought=most_bought,
        grand_total=grand_total,
        user_info=user_info,
        locked_users=locked_users,
        admin=True,
        user=session["user"]
    )

# =====================
# START
# =====================
if __name__ == "__main__":
    socketio.run(app, debug=True)

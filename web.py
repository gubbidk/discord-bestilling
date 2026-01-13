import os
import json
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO

from db import (
    init_db,
    load_sessions,
    save_sessions,
    load_access,
    save_access,
    load_lager,
    load_prices,
    load_user_stats,
    save_user_stats,
    audit_log
)

init_db()

# =====================
# KONFIG
# =====================
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_ADMIN_ROLE = os.getenv("DISCORD_ADMIN_ROLE")
DISCORD_USER_ROLE = os.getenv("DISCORD_USER_ROLE")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_TOKEN")

OAUTH_REDIRECT = "/auth/callback"

# =====================
# FLASK
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*")

# =====================
# HELPERS
# =====================
def is_admin():
    return session.get("admin", False)

def is_blocked(uid):
    return uid in load_access()["blocked"]

def get_user_statistics(uid):
    stats = load_user_stats().get(uid, {
        "total_spent": 0,
        "total_items": 0,
        "items": {}
    })

    most_bought = max(stats["items"], key=stats["items"].get) if stats["items"] else None

    sessions = load_sessions()
    locked = False
    if sessions["current"]:
        locked = uid in sessions["sessions"][sessions["current"]]["locked_users"]

    role = load_access()["users"].get(uid, {}).get("role", "user")

    return {
        "total_spent": stats["total_spent"],
        "total_items": stats["total_items"],
        "most_bought": most_bought,
        "locked": locked,
        "role": role
    }

def get_lager_status_for_session(session_name):
    data = load_sessions()
    session_data = data["sessions"].get(session_name)
    if not session_data:
        return {}

    lager = load_lager()
    used = {i: 0 for i in lager}

    for o in session_data["orders"]:
        for item, amount in o.get("items", {}).items():
            used[item] += amount

    status = {}
    for item, max_amount in lager.items():
        left = max(0, max_amount - used[item])
        pct = 0 if max_amount == 0 else left / max_amount
        status[item] = {
            "left": left,
            "max": max_amount,
            "level": "danger" if left <= 0 else "warning" if pct < 0.3 else "ok"
        }
    return status

# =====================
# BLOCK ENFORCEMENT
# =====================
@app.before_request
def enforce_blocked():
    if "user" in session and is_blocked(session["user"]["id"]):
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

    roles = member.json()["roles"]
    role_data = requests.get(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    ).json()

    role_map = {r["id"]: r["name"] for r in role_data}

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
# ROUTES
# =====================
@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")

    data = load_sessions()
    totals = {
        name: sum(o.get("total", 0) for o in s["orders"])
        for name, s in data["sessions"].items()
    }

    return render_template(
        "index.html",
        sessions=data["sessions"],
        totals=totals,
        current=data["current"],
        admin=is_admin(),
        user=session["user"],
        stats=get_user_statistics(session["user"]["id"])
    )

@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return "Forbidden", 403
    return render_template("admin_dashboard.html", admin=True, user=session["user"])

@app.route("/admin/user_history")
def user_history():
    if not is_admin():
        return "Forbidden", 403

    uid = request.args.get("uid")
    sessions = load_sessions()
    access = load_access()
    orders = []

    if uid:
        for sname, s in sessions["sessions"].items():
            for o in s["orders"]:
                if o.get("user_id") == uid:
                    orders.append({
                        "session": sname,
                        "items": o["items"],
                        "total": o["total"],
                        "time": o["time"]
                    })

    stats = get_user_statistics(uid) if uid else None

    return render_template(
        "user_history.html",
        uid=uid,
        orders=orders,
        stats=stats,
        grand_total=stats["total_spent"] if stats else 0,
        user_info=access["users"].get(uid),
        locked_users=sessions["sessions"].get(sessions["current"], {}).get("locked_users", []),
        admin=True,
        user=session["user"]
    )

@app.route("/session/<name>")
def view_session(name):
    if "user" not in session:
        return redirect("/login")

    data = load_sessions()
    if name not in data["sessions"]:
        return "Findes ikke", 404

    orders = data["sessions"][name]["orders"]
    total = sum(o["total"] for o in orders)

    return render_template(
        "session.html",
        name=name,
        orders=orders,
        total=total,
        lager_status=get_lager_status_for_session(name),
        admin=is_admin(),
        user=session["user"]
    )

@app.route("/session_data/<name>")
def session_data(name):
    data = load_sessions()
    orders = data["sessions"].get(name, {}).get("orders", [])
    payload = json.dumps(orders, sort_keys=True)
    return jsonify({"hash": hashlib.md5(payload.encode()).hexdigest()})

# =====================
# START
# =====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)

import os
import json
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO
from db import init_db, get_conn

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
# DB HELPERS
# =====================
def load_sessions():
    with get_conn() as conn:
        c = conn.cursor()

        cur = c.execute("SELECT value FROM meta WHERE key='current'").fetchone()
        current = None if not cur else json.loads(cur[0])

        sessions = {}
        for name, open_, data in c.execute("SELECT name, open, data FROM sessions"):
            s = json.loads(data)
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
                (name, int(s.get("open", False)), json.dumps(s))
            )

        c.execute(
            "INSERT OR REPLACE INTO meta VALUES ('current', ?)",
            (json.dumps(data.get("current")),)
        )
        conn.commit()

    socketio.emit("update")

def load_lager():
    with get_conn() as conn:
        return dict(conn.execute("SELECT item, amount FROM lager"))

def load_prices():
    with get_conn() as conn:
        return dict(conn.execute("SELECT item, price FROM prices"))

def load_user_stats():
    with get_conn() as conn:
        return {
            uid: json.loads(data)
            for uid, data in conn.execute("SELECT user_id, data FROM user_stats")
        }

def save_user_stats(stats):
    with get_conn() as conn:
        c = conn.cursor()
        for uid, data in stats.items():
            c.execute(
                "INSERT OR REPLACE INTO user_stats VALUES (?, ?)",
                (uid, json.dumps(data))
            )
        conn.commit()

def load_access():
    with get_conn() as conn:
        users = {
            uid: json.loads(data)
            for uid, data in conn.execute("SELECT user_id, data FROM access")
        }
        blocked = [uid for (uid,) in conn.execute("SELECT user_id FROM blocked")]
        return {"users": users, "blocked": blocked}

def save_access(data):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM access")
        c.execute("DELETE FROM blocked")

        for uid, udata in data["users"].items():
            c.execute(
                "INSERT INTO access VALUES (?, ?)",
                (uid, json.dumps(udata))
            )

        for uid in data["blocked"]:
            c.execute("INSERT OR IGNORE INTO blocked VALUES (?)", (uid,))
        conn.commit()

def load_audit():
    with get_conn() as conn:
        return [
            {
                "time": t,
                "action": a,
                "admin": ad,
                "target": tg
            }
            for t, a, ad, tg in conn.execute(
                "SELECT time, action, admin, target FROM audit ORDER BY id DESC"
            )
        ]

def audit_log(action, admin, target):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit (time, action, admin, target) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%d-%m-%Y %H:%M"), action, admin, target)
        )
        conn.commit()

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

    headers = {"Authorization": f"Bearer {token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers).json()

    member = requests.get(
        f"https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member",
        headers=headers
    )
    if member.status_code != 200:
        return "Ikke medlem", 403

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
# ROUTES (ALLE DE MANGLENDE)
# =====================
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
    user_info = access["users"].get(uid)

    return render_template(
        "user_history.html",
        uid=uid,
        orders=orders,
        stats=stats,
        grand_total=stats["total_spent"] if stats else 0,
        user_info=user_info,
        locked_users=sessions["sessions"].get(sessions["current"], {}).get("locked_users", []),
        admin=True,
        user=session["user"]
    )

@app.route("/admin/lock/<uid>")
def admin_lock_user(uid):
    data = load_sessions()
    current = data["current"]
    if current and uid not in data["sessions"][current]["locked_users"]:
        data["sessions"][current]["locked_users"].append(uid)
        save_sessions(data)
        audit_log("lock_user", session["user"]["name"], uid)
    return redirect(f"/admin/user_history?uid={uid}")

@app.route("/admin/unlock/<uid>")
def admin_unlock_user(uid):
    data = load_sessions()
    current = data["current"]
    if current and uid in data["sessions"][current]["locked_users"]:
        data["sessions"][current]["locked_users"].remove(uid)
        save_sessions(data)
        audit_log("unlock_user", session["user"]["name"], uid)
    return redirect(f"/admin/user_history?uid={uid}")

@app.route("/open_session")
def open_session():
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    if data["current"]:
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": [], "locked_users": []}
    data["current"] = name

    save_sessions(data)
    audit_log("open_session", session["user"]["name"], name)
    return redirect("/")

@app.route("/close_session")
def close_session():
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    if data["current"]:
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

    data = load_sessions()
    if name in data["sessions"]:
        del data["sessions"][name]
        if data["current"] == name:
            data["current"] = None
        save_sessions(data)
        audit_log("delete_session", session["user"]["name"], name)

    return redirect("/")

@app.route("/admin/users")
def admin_users():
    if not is_admin():
        return "Forbidden", 403

    access = load_access()
    users = dict(sorted(
        access["users"].items(),
        key=lambda x: (0 if x[1]["role"] == "admin" else 1, x[1]["name"].lower())
    ))

    return render_template(
        "admin_users.html",
        users=users,
        blocked=access["blocked"],
        admin=True,
        user=session["user"]
    )

@app.route("/admin/block/<uid>")
def block_user(uid):
    access = load_access()
    if uid not in access["blocked"]:
        access["blocked"].append(uid)
        save_access(access)
        audit_log("block", session["user"]["name"], uid)
    return redirect("/admin/users")

@app.route("/admin/unblock/<uid>")
def unblock_user(uid):
    access = load_access()
    if uid in access["blocked"]:
        access["blocked"].remove(uid)
        save_access(access)
        audit_log("unblock", session["user"]["name"], uid)
    return redirect("/admin/users")

@app.route("/admin/audit")
def audit():
    if not is_admin():
        return "Forbidden", 403
    return render_template("audit.html", events=load_audit())

# =====================
# START
# =====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)

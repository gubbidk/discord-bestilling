import os
import json
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, session, jsonify

# =====================
# KONFIGURATION
# =====================
SESSIONS_FILE = "sessions.json"
ACCESS_FILE = "access.json"
AUDIT_FILE = "audit.json"
LAGER_FILE = "lager.json"
PRICES_FILE = "prices.json"

ADMIN_KEY = os.getenv("ADMIN_KEY", "thomas")

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

# =====================
# HJÆLPERE
# =====================

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

def load_lager():
    return load_json(LAGER_FILE, {})

def load_prices():
    return load_json(PRICES_FILE, {})

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
        return "Du er ikke medlem af Discord-serveren", 403

    if is_blocked(user["id"]):
        return "Du er blokeret fra web-panelet", 403

    roles = member.json().get("roles", [])

    guild_roles = requests.get(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles",
        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    ).json()

    role_map = {r["id"]: r["name"] for r in guild_roles}

    admin = False
    access = False

    for r in roles:
        name = role_map.get(r)
        if name == DISCORD_ADMIN_ROLE:
            admin = True
            access = True
        if name == DISCORD_USER_ROLE:
            access = True

    if not access:
        return "Ingen adgang til web-panelet", 403

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

    # ===== LAGERSTATUS (NY) =====
    lager = load_lager()

    # brugt pr vare
    used = {}
    for o in orders:
        for item, amount in o.get("items", {}).items():
            used[item] = used.get(item, 0) + amount

    lager_status = {}
    for item, max_amount in lager.items():
        u = used.get(item, 0)
        left = max(0, max_amount - u)

        if left <= 0:
            level = "danger"
        elif left <= max_amount * 0.25:
            level = "warn"
        else:
            level = "ok"

        lager_status[item] = {
            "max": max_amount,
            "used": u,
            "left": left,
            "level": level
        }

    total = sum(o.get("total", 0) for o in orders)

    return render_template(
        "session.html",
        name=name,
        orders=orders,
        total=total,
        lager_status=lager_status,   # ✅ VIGTIG
        admin=is_admin(),
        user=session["user"]
    )


@app.route("/edit_order/<session_name>/<order_id>", methods=["GET", "POST"])
def edit_order(session_name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    s = data["sessions"].get(session_name)
    if not s:
        return "Not found", 404

    order = next((o for o in s["orders"] if o["id"] == order_id), None)
    if not order:
        return "Order not found", 404

    lager = load_lager()
    prices = load_prices()

    if request.method == "POST":
        total = 0
        for item in order["items"]:
            req = int(request.form.get(item, 0))
            used = sum(
                o["items"].get(item, 0)
                for o in s["orders"]
                if o["id"] != order_id
            )
            max_allowed = max(0, lager.get(item, 0) - used)
            final = min(req, max_allowed)
            order["items"][item] = final
            total += final * prices.get(item, 0)

        order["total"] = total
        save_sessions(data)

        audit_log("edit_order", session["user"]["name"], f"{session_name}:{order_id}")

        return redirect(f"/session/{session_name}")

    return render_template(
        "edit_order.html",
        session=session_name,
        order=order,
        prices=prices,
        admin=True,
        user=session["user"]
    )

@app.route("/delete_order/<session_name>/<order_id>")
def delete_order(session_name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    s = data["sessions"].get(session_name)
    if not s:
        return "Not found", 404

    s["orders"] = [o for o in s["orders"] if o["id"] != order_id]
    save_sessions(data)

    audit_log("delete_order", session["user"]["name"], f"{session_name}:{order_id}")

    return redirect(f"/session/{session_name}")

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

@app.route("/admin/block/<discord_id>")
def block_user(discord_id):
    if not is_admin():
        return "Forbidden", 403

    access = load_access()
    if discord_id not in access["blocked"]:
        access["blocked"].append(discord_id)
        save_access(access)
        audit_log("block", session["user"]["name"], discord_id)

    return redirect("/")

@app.route("/admin/unblock/<discord_id>")
def unblock_user(discord_id):
    if not is_admin():
        return "Forbidden", 403

    access = load_access()
    if discord_id in access["blocked"]:
        access["blocked"].remove(discord_id)
        save_access(access)
        audit_log("unblock", session["user"]["name"], discord_id)

    return redirect("/")

@app.route("/admin/audit")
def audit():
    if not is_admin():
        return "Forbidden", 403
    return render_template("audit.html", events=reversed(load_audit()["events"]))

@app.route("/session_data/<name>")
def session_data(name):
    data = normalize(load_sessions())
    orders = data["sessions"].get(name, {}).get("orders", [])
    payload = json.dumps(orders, sort_keys=True)
    return jsonify({"hash": hashlib.md5(payload.encode()).hexdigest()})

@app.route("/admin/users")
def admin_users():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    access = load_access()
    users = {}

    for s in data["sessions"].values():
        for o in s.get("orders", []):
            uid = o.get("user_id")
            if uid:
                users[uid] = o.get("user")

    return render_template(
        "admin_users.html",
        users=users,
        blocked=access.get("blocked", []),
        user=session["user"],
        admin=True
    )

# =====================
# START
# =====================
if __name__ == "__main__":
    app.run(debug=True)

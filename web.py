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

def get_user_statistics(uid):
    access = load_access()
    user_info = access["users"].get(uid)
    if not user_info:
        return None

    data = load_sessions()

    total_spent = 0
    total_items = 0
    item_counter = {}

    for s in data["sessions"].values():
        for o in s["orders"]:
            if o.get("user_id") == uid:
                total_spent += o.get("total", 0)

                for item, amount in o.get("items", {}).items():
                    total_items += amount
                    if item.lower() != "veste":
                        item_counter[item] = item_counter.get(item, 0) + amount

    most_bought = None
    if item_counter:
        most_bought = max(item_counter.items(), key=lambda x: x[1])[0]

    return {
        "name": user_info["name"],
        "role": user_info["role"],
        "total_spent": total_spent,
        "total_items": total_items,
        "most_bought": most_bought
    }


def is_admin():
    return session.get("admin", False)

def is_blocked(uid):
    return uid in load_access().get("blocked", [])

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
# DEDIKERET LAGER (PR SESSION)
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
            if item in used:
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
# BLOCK-ENFORCEMENT
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

    if resp.status_code != 200:
        return "Discord rolle-fejl", 500

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

@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return "Forbidden", 403

    return render_template(
        "admin_dashboard.html",
        admin=True,
        user=session["user"]
    )


@app.route("/admin/user_history")
def user_history():
    if not is_admin():
        return "Forbidden", 403

    uid = request.args.get("uid")
    orders = []
    stats = None
    most_bought = None
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

        stats = get_user_statistics(uid)
        if stats:
            grand_total = stats["total_spent"]
            most_bought = stats["most_bought"]

    # ✅ BRUGERINFO (FIX)
    access = load_access()
    raw_user = access["users"].get(uid)

    user_info = None
    if raw_user:
        user_info = {
            "name": raw_user.get("name"),
            "role": raw_user.get("role"),
            "avatar": session["user"].get("avatar")
        }

    # ✅ FALLBACK STATS (VIGTIG)
    if not stats:
        stats = {
            "total_spent": 0,
            "total_items": 0
        }

    locked_users = []
    current = load_sessions().get("current")
    if current:
        locked_users = load_sessions()["sessions"][current].get("locked_users", [])

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







@app.route("/admin/lock/<uid>")
def admin_lock_user(uid):
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    current = data.get("current")
    if not current:
        return redirect("/admin/users")

    session_data = data["sessions"][current]
    session_data.setdefault("locked_users", [])

    if uid not in session_data["locked_users"]:
        session_data["locked_users"].append(uid)
        save_sessions(data)
        audit_log("lock_user", session["user"]["name"], uid)

    return redirect(f"/admin/user_history?uid={uid}")


@app.route("/admin/unlock/<uid>")
def admin_unlock_user(uid):
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    current = data.get("current")
    if not current:
        return redirect("/admin/users")

    session_data = data["sessions"][current]
    session_data.setdefault("locked_users", [])

    if uid in session_data["locked_users"]:
        session_data["locked_users"].remove(uid)
        save_sessions(data)
        audit_log("unlock_user", session["user"]["name"], uid)

    return redirect(f"/admin/user_history?uid={uid}")



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
    lager_status = get_lager_status_for_session(name)
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

    data = load_sessions()
    if data["current"]:
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {
    "open": True,
    "orders": [],
    "locked_users": []
}
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

@app.route("/delete_order/<session_name>/<order_id>")
def delete_order(session_name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    session_data = data["sessions"].get(session_name)
    if not session_data:
        return "Session not found", 404

    orders = session_data.get("orders", [])

    order = next((o for o in orders if o["id"] == order_id), None)
    if not order:
        return "Order not found", 404

    # 🔁 Snapshot af items (bruges til audit)
    returned_items = {
        item: amount
        for item, amount in order.get("items", {}).items()
        if amount > 0
    }

    # ❌ Fjern ordren
    session_data["orders"] = [
        o for o in orders if o["id"] != order_id
    ]

    save_sessions(data)

    # 🧾 Audit
    if returned_items:
        details = "Returneret til lager:\n- " + "\n- ".join(
            f"{k}: {v}" for k, v in returned_items.items()
        )
    else:
        details = "Ingen varer i ordren"

    audit_log(
        "delete_order",
        session["user"]["name"],
        f"{session_name}:{order_id}\n{details}"
    )

    return redirect(f"/session/{session_name}")

@app.route("/edit_order/<session_name>/<order_id>", methods=["GET", "POST"])
def edit_order(session_name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    session_data = data["sessions"].get(session_name)
    if not session_data:
        return "Session not found", 404

    orders = session_data.get("orders", [])

    order = next((o for o in orders if o["id"] == order_id), None)
    if not order:
        return "Order not found", 404

    prices = load_prices()
    lager = load_lager()

    # =====================
    # POST – GEM ÆNDRINGER
    # =====================
    if request.method == "POST":
        before_items = order["items"].copy()

        # 🔁 beregn brugt lager i DENNE session
        used = {}
        for o in orders:
            for item, amount in o.get("items", {}).items():
                used[item] = used.get(item, 0) + amount

        total = 0

        for item in order["items"]:
            requested = int(request.form.get(item, 0))

            # hvor meget er brugt af ANDRE ordrer
            used_by_others = used.get(item, 0) - before_items.get(item, 0)

            max_allowed = max(0, lager.get(item, 0) - used_by_others)
            final_amount = min(requested, max_allowed)

            order["items"][item] = final_amount
            total += final_amount * prices.get(item, 0)

        order["total"] = total
        save_sessions(data)

        # 🧾 audit
        changes = []
        for k in order["items"]:
            if before_items.get(k, 0) != order["items"].get(k, 0):
                changes.append(
                    f"{k}: {before_items.get(k, 0)} → {order['items'][k]}"
                )

        audit_log(
            "edit_order",
            session["user"]["name"],
            f"{session_name}:{order_id}\n"
            + ("Ændringer:\n- " + "\n- ".join(changes) if changes else "Ingen ændringer")
        )

        return redirect(f"/session/{session_name}")

    # =====================
    # GET – VIS FORMULAR
    # =====================
    return render_template(
        "edit_order.html",
        session=session_name,
        order=order,
        prices=prices,
        admin=True,
        user=session["user"]
    )


@app.route("/delete_session/<name>")
def delete_session(name):
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    if name not in data["sessions"]:
        return "Not found", 404

    if data["current"] == name:
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
    users = dict(
        sorted(
            access["users"].items(),
            key=lambda x: (0 if x[1]["role"] == "admin" else 1, x[1]["name"].lower())
        )
    )

    return render_template(
        "admin_users.html",
        users=users,
        blocked=access["blocked"],
        admin=True,
        user=session["user"]
    )

@app.route("/admin/block/<uid>")
def block_user(uid):
    if not is_admin():
        return "Forbidden", 403

    access = load_access()
    if uid not in access["blocked"]:
        access["blocked"].append(uid)
        save_access(access)
        audit_log("block", session["user"]["name"], uid)

    return redirect("/admin/users")

@app.route("/admin/unblock/<uid>")
def unblock_user(uid):
    if not is_admin():
        return "Forbidden", 403

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

    events = list(reversed(load_audit()["events"]))
    action = request.args.get("action")
    if action:
        events = [e for e in events if e["action"] == action]

    return render_template("audit.html", events=events)

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
    socketio.run(app, debug=True)

import os
import json
import hashlib
from flask import Flask, render_template, request, redirect, session, jsonify

# =====================
# KONFIGURATION
# =====================
SESSIONS_FILE = "sessions.json"
ADMIN_KEY = os.getenv("ADMIN_KEY", "thomas")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

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


def is_admin():
    return session.get("admin", False)

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    data = normalize(load_sessions())
    return render_template(
        "index.html",
        sessions=list(data["sessions"].keys()),
        current=data["current"],
        admin=is_admin()
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


# =====================
# START
# =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

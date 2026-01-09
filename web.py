import os
import json
import hashlib
import requests
from flask import Flask, render_template, request, redirect, session, jsonify

# =====================
# KONFIG
# =====================
SESSIONS_FILE = "sessions.json"
ADMIN_KEY = "thomas"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

PRICES = json.load(open("prices.json", "r", encoding="utf-8"))

# =====================
# FLASK
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key")

# =====================
# FIL-HJÆLPERE
# =====================
def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        data = {"current": None, "sessions": {}}
        save_sessions(data)
        return data

    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sessions(data):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def normalize(data):
    data.setdefault("sessions", {})
    for name, val in data["sessions"].items():
        if isinstance(val, list):
            data["sessions"][name] = {"open": False, "orders": val}
        else:
            val.setdefault("open", False)
            val.setdefault("orders", [])
    return data


def is_admin():
    return session.get("admin", False)


def send_discord(msg):
    if DISCORD_WEBHOOK.startswith("http"):
        requests.post(DISCORD_WEBHOOK, json={"content": msg})


def calc_total(items):
    return sum(PRICES.get(i, 0) * a for i, a in items.items())

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    data = normalize(load_sessions())
    return render_template(
        "index.html",
        sessions=list(data["sessions"].keys()),
        current=data.get("current"),
        is_admin=is_admin()
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

    if data.get("current"):
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": []}
    data["current"] = name

    save_sessions(data)
    send_discord(f"🟢 **{name} åbnet**")

    return redirect("/")


@app.route("/close_session")
def close_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load_sessions())
    if data.get("current"):
        send_discord(f"🔴 **{data['current']} lukket**")
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
        if data.get("current") == name:
            data["current"] = None
        save_sessions(data)
        send_discord(f"🗑️ **{name} slettet**")

    return redirect("/")


@app.route("/session/<name>")
def session_view(name):
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
        is_admin=is_admin()
    )
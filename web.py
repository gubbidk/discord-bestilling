from flask import Flask, render_template, redirect, request, session, jsonify
from data import load_sessions, save_sessions
import json
import hashlib

app = Flask(__name__)
app.secret_key = "fedko"

ADMIN_KEY = "thomas"

with open("prices.json") as f:
    PRICES = json.load(f)

def is_admin():
    return session.get("admin", False)

@app.route("/")
def index():
    data = load_sessions()
    return render_template(
        "index.html",
        sessions=data["sessions"].keys(),
        current=data.get("current"),
        admin=is_admin()
    )

@app.route("/admin")
def admin_login():
    if request.args.get("key") != ADMIN_KEY:
        return "Forkert nøgle", 403
    session["admin"] = True
    return redirect("/")

@app.route("/open_session")
def open_session():
    if not is_admin():
        return "Forbidden", 403

    data = load_sessions()
    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": []}
    data["current"] = name
    save_sessions(data)
    return redirect("/")

@app.route("/session/<name>")
def session_view(name):
    data = load_sessions()
    orders = data["sessions"][name]["orders"]
    total = sum(o["total"] for o in orders)

    return render_template(
        "session.html",
        name=name,
        orders=orders,
        total=total,
        admin=is_admin()
    )

@app.route("/session_data/<name>")
def session_data(name):
    data = load_sessions()
    orders = data["sessions"][name]["orders"]
    payload = json.dumps(orders, sort_keys=True)
    return jsonify({
        "hash": hashlib.md5(payload.encode()).hexdigest()
    })

if __name__ == "__main__":
    app.run()

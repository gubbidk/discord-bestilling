from flask import (
    Flask, render_template, request,
    redirect, session as flask_session, jsonify
)
import os
import json
import hashlib
import requests
from data import load, save, calc_total

# =====================
# KONFIG
# =====================
ADMIN_KEY = "thomas"  # skift hvis du vil
DISCORD_WEBHOOK = "INDSÆT_DIN_WEBHOOK_URL_HER"

SESSIONS_FILE = "sessions.json"
PRICES = load("prices.json")

app = Flask(__name__)
app.secret_key = "super-secret-key"


# =====================
# HJÆLPERE
# =====================
def is_admin():
    return flask_session.get("admin", False)


def send_discord(msg):
    if DISCORD_WEBHOOK.startswith("http"):
        requests.post(DISCORD_WEBHOOK, json={"content": msg})


def normalize(data):
    """
    Sikrer format:
    sessions[name] = { open: bool, orders: [...] }
    """
    if "sessions" not in data:
        data["sessions"] = {}

    for name, val in data["sessions"].items():
        if isinstance(val, list):
            data["sessions"][name] = {
                "open": False,
                "orders": val
            }
        else:
            data["sessions"][name].setdefault("open", False)
            data["sessions"][name].setdefault("orders", [])

    return data


# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    data = normalize(load(SESSIONS_FILE))
    return render_template(
        "index.html",
        sessions=list(data["sessions"].keys()),
        current=data.get("current"),
        admin=is_admin()
    )


@app.route("/admin")
def admin_login():
    if request.args.get("key") != ADMIN_KEY:
        return "❌ Forkert admin-nøgle", 403

    flask_session["admin"] = True
    return redirect("/")


@app.route("/open_session")
def open_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))

    if data.get("current"):
        data["sessions"][data["current"]]["open"] = False

    i = 1
    while f"bestilling{i}" in data["sessions"]:
        i += 1

    name = f"bestilling{i}"
    data["sessions"][name] = {"open": True, "orders": []}
    data["current"] = name

    save(SESSIONS_FILE, data)
    send_discord(f"🟢 **{name} åbnet**")

    return redirect("/")


@app.route("/close_session")
def close_session():
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))
    if data.get("current"):
        send_discord(f"🔴 **{data['current']} lukket**")
        data["sessions"][data["current"]]["open"] = False
        data["current"] = None
        save(SESSIONS_FILE, data)

    return redirect("/")


@app.route("/delete_session/<name>")
def delete_session(name):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))

    if name in data["sessions"]:
        del data["sessions"][name]
        if data.get("current") == name:
            data["current"] = None
        save(SESSIONS_FILE, data)
        send_discord(f"🗑️ **{name} slettet**")

    return redirect("/")


@app.route("/session/<name>")
def session_view(name):
    data = normalize(load(SESSIONS_FILE))

    if name not in data["sessions"]:
        return "Findes ikke", 404

    orders = data["sessions"][name]["orders"]
    total = sum(o.get("total", 0) for o in orders)

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

    data = normalize(load(SESSIONS_FILE))
    orders = data["sessions"][name]["orders"]
    order = next((o for o in orders if o["id"] == order_id), None)

    if not order:
        return "Ordre findes ikke", 404

    if request.method == "POST":
        for item in order["items"]:
            order["items"][item] = int(request.form.get(item, 0))
        order["total"] = calc_total(order["items"])

        save(SESSIONS_FILE, data)
        send_discord(
            f"✏️ **Ordre opdateret** ({order['user']})\n"
            f"💰 Ny total: {order['total']:,} kr"
        )
        return redirect(f"/session/{name}")

    return render_template(
        "edit_order.html",
        order=order,
        session=name,
        prices=PRICES,
        admin=True
    )


@app.route("/delete_order/<name>/<order_id>")
def delete_order(name, order_id):
    if not is_admin():
        return "Forbidden", 403

    data = normalize(load(SESSIONS_FILE))
    orders = data["sessions"][name]["orders"]

    order = next((o for o in orders if o["id"] == order_id), None)
    data["sessions"][name]["orders"] = [
        o for o in orders if o["id"] != order_id
    ]

    save(SESSIONS_FILE, data)

    if order:
        items = "\n".join(
            f"- {k}: {v}"
            for k, v in order["items"].items() if v > 0
        )
        send_discord(
            f"🗑️ **Ordre slettet** ({order['user']})\n{items}"
        )

    return redirect(f"/session/{name}")


@app.route("/session_data/<name>")
def session_data(name):
    data = normalize(load(SESSIONS_FILE))
    orders = data["sessions"].get(name, {}).get("orders", [])

    payload = json.dumps(orders, sort_keys=True)
    return jsonify({
        "hash": hashlib.md5(payload.encode()).hexdigest()
    })


if __name__ == "__main__":
    app.run(debug=True)

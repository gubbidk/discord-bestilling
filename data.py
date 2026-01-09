import json
import os
from datetime import datetime

SESSIONS_FILE = "sessions.json"

def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "w") as f:
            json.dump({"current": None, "sessions": {}}, f)
    with open(SESSIONS_FILE, "r") as f:
        return json.load(f)

def save_sessions(data):
    with open(SESSIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def new_order(user, items):
    return {
        "id": str(datetime.now().timestamp()),
        "user": user,
        "items": items,
        "total": 0,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M")
    }

def calc_total(items, prices):
    return sum(items[i] * prices.get(i, 0) for i in items)

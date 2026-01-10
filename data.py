import json
import os
from datetime import datetime

DATA_DIR = "/data"

SESSIONS_FILE = f"{DATA_DIR}/sessions.json"
ACCESS_FILE   = f"{DATA_DIR}/access.json"
AUDIT_FILE    = f"{DATA_DIR}/audit.json"

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

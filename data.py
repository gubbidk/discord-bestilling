import json, os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))

def load(name):
    with open(os.path.join(BASE, name), "r", encoding="utf-8") as f:
        return json.load(f)

def save(name, data):
    with open(os.path.join(BASE, name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def calc_total(items):
    prices = load("prices.json")
    return sum(prices.get(i, 0) * a for i, a in items.items())

def new_order(user, items):
    return {
        "id": str(datetime.now().timestamp()),
        "user": user,
        "items": items,
        "total": calc_total(items),
        "time": datetime.now().strftime("%d-%m-%Y %H:%M")
    }

def ensure_order_integrity(order):
    order["total"] = calc_total(order["items"])

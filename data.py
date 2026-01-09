import json
import os
from datetime import datetime

BASE = os.path.dirname(__file__)

def load(filename):
    path = os.path.join(BASE, filename)
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save(filename, data):
    path = os.path.join(BASE, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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

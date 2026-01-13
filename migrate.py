import json, os
from db import get_conn, init_db, DATA_DIR

init_db()

def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

with get_conn() as conn:
    c = conn.cursor()

    # sessions.json
    sessions = load(f"{DATA_DIR}/sessions.json", {"current": None, "sessions": {}})
    c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", ("current", json.dumps(sessions["current"])))
    for name, s in sessions["sessions"].items():
        c.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
            (name, int(s.get("open", False)), json.dumps(s))
        )

    # lager.json
    for k, v in load(f"{DATA_DIR}/lager.json", {}).items():
        c.execute("INSERT OR REPLACE INTO lager VALUES (?, ?)", (k, v))

    # prices.json
    for k, v in load(f"{DATA_DIR}/prices.json", {}).items():
        c.execute("INSERT OR REPLACE INTO prices VALUES (?, ?)", (k, v))

    # user_stats.json
    for uid, data in load(f"{DATA_DIR}/user_stats.json", {}).items():
        c.execute("INSERT OR REPLACE INTO user_stats VALUES (?, ?)", (uid, json.dumps(data)))

    # access.json
    access = load(f"{DATA_DIR}/access.json", {"users": {}, "blocked": []})
    for uid, data in access.get("users", {}).items():
        c.execute("INSERT OR REPLACE INTO access VALUES (?, ?)", (uid, json.dumps(data)))
    for uid in access.get("blocked", []):
        c.execute("INSERT OR IGNORE INTO blocked VALUES (?)", (uid,))

    # audit.json
    for e in load(f"{DATA_DIR}/audit.json", {"events": []}).get("events", []):
        c.execute(
            "INSERT INTO audit (time, action, admin, target) VALUES (?, ?, ?, ?)",
            (e["time"], e["action"], e["admin"], e["target"])
        )

    conn.commit()

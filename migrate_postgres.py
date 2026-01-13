import json
import os
import psycopg2
from db import get_conn, init_db

DATA_DIR = "/data"

init_db()

def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

with get_conn() as conn:
    with conn.cursor() as c:

        sessions = load(f"{DATA_DIR}/sessions.json", {"current": None, "sessions": {}})
        c.execute(
            "INSERT INTO meta VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=%s",
            ("current", sessions["current"], sessions["current"])
        )

        for name, s in sessions["sessions"].items():
            c.execute(
                "INSERT INTO sessions VALUES (%s, %s, %s) "
                "ON CONFLICT (name) DO UPDATE SET open=%s, data=%s",
                (name, s.get("open", False), json.dumps(s), s.get("open", False), json.dumps(s))
            )

        for k, v in load(f"{DATA_DIR}/lager.json", {}).items():
            c.execute(
                "INSERT INTO lager VALUES (%s, %s) ON CONFLICT (item) DO UPDATE SET amount=%s",
                (k, v, v)
            )

        for k, v in load(f"{DATA_DIR}/prices.json", {}).items():
            c.execute(
                "INSERT INTO prices VALUES (%s, %s) ON CONFLICT (item) DO UPDATE SET price=%s",
                (k, v, v)
            )

        for uid, data in load(f"{DATA_DIR}/user_stats.json", {}).items():
            c.execute(
                "INSERT INTO user_stats VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET data=%s",
                (uid, json.dumps(data), json.dumps(data))
            )

        access = load(f"{DATA_DIR}/access.json", {"users": {}, "blocked": []})
        for uid, data in access["users"].items():
            c.execute(
                "INSERT INTO access VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET data=%s",
                (uid, json.dumps(data), json.dumps(data))
            )

        for uid in access["blocked"]:
            c.execute(
                "INSERT INTO blocked VALUES (%s) ON CONFLICT DO NOTHING",
                (uid,)
            )

        for e in load(f"{DATA_DIR}/audit.json", {"events": []})["events"]:
            c.execute(
                "INSERT INTO audit (time, action, admin, target) VALUES (%s, %s, %s, %s)",
                (e["time"], e["action"], e["admin"], e["target"])
            )

    conn.commit()

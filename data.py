import json
from datetime import datetime
from db import get_conn


# =====================
# SESSIONS
# =====================
def load_sessions():
    """
    Returnerer:
    {
        "current": <session_name | None>,
        "sessions": {
            session_name: {
                "open": bool,
                "orders": [...],
                "locked_users": [...]
            }
        }
    }
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            # current session
            c.execute("SELECT value FROM meta WHERE key='current'")
            row = c.fetchone()
            current = row[0] if row else None

            sessions = {}
            c.execute("SELECT name, open, data FROM sessions")
            for name, open_, data in c.fetchall():
                data["open"] = open_
                data.setdefault("orders", [])
                data.setdefault("locked_users", [])
                sessions[name] = data

            return {
                "current": current,
                "sessions": sessions
            }


def save_sessions(data):
    with get_conn() as conn:
        with conn.cursor() as c:
            # wipe & rewrite (samme adfærd som JSON-version)
            c.execute("DELETE FROM sessions")

            for name, s in data["sessions"].items():
                c.execute(
                    """
                    INSERT INTO sessions (name, open, data)
                    VALUES (%s, %s, %s)
                    """,
                    (name, s.get("open", False), json.dumps(s))
                )

            c.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('current', %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
                """,
                (json.dumps(data.get("current")),)
            )

        conn.commit()


# =====================
# ORDERS
# =====================
def new_order(user, items, user_id=None):
    """
    Matcher den gamle JSON-struktur 1:1
    """
    return {
        "id": str(datetime.now().timestamp()),
        "user": user,
        "user_id": user_id,
        "items": items,
        "total": 0,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M")
    }


def calc_total(items, prices):
    """
    Uændret logik – bare uden filsystem
    """
    return sum(items[i] * prices.get(i, 0) for i in items)

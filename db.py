import os
import json
import psycopg2
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

# =====================
# CONNECTION
# =====================
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# =====================
# INIT
# =====================
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        # meta table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # sessions table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            data JSONB
        )
        """)

        # access table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS access (
            id SERIAL PRIMARY KEY,
            data JSONB
        )
        """)

        # lager table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lager (
            id SERIAL PRIMARY KEY,
            data JSONB
        )
        """)

        # prices table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id SERIAL PRIMARY KEY,
            data JSONB
        )
        """)

        # user stats
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            id SERIAL PRIMARY KEY,
            data JSONB
        )
        """)

        # audit log
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id SERIAL PRIMARY KEY,
            data JSONB
        )
        """)

        # 🔑 sikre default meta rows
        cur.execute("""
        INSERT INTO meta (key, value)
        VALUES ('current', NULL)
        ON CONFLICT (key) DO NOTHING
        """)

        conn.commit()



# =====================
# SESSIONS FUCK AEJJEJEADADAERTGGG
# =====================

def load_sessions():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT value FROM meta WHERE key='current'")
        row = cur.fetchone()

        current = row[0] if row else None

        cur.execute("SELECT data FROM sessions ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()

        if row and row[0]:
            data = row[0]
        else:
            data = {
                "current": None,
                "sessions": {}
            }

        data["current"] = current
        return data




def save_sessions(data):
    with get_conn() as conn:
        with conn.cursor() as c:
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
# LAGER & PRICES
# =====================
def load_lager():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT item, amount FROM lager")
            return dict(c.fetchall())


def load_prices():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT item, price FROM prices")
            return dict(c.fetchall())


# =====================
# USER STATS
# =====================
def load_user_stats():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT user_id, data FROM user_stats")
            return {uid: data for uid, data in c.fetchall()}


def save_user_stats(stats):
    with get_conn() as conn:
        with conn.cursor() as c:
            for uid, data in stats.items():
                c.execute(
                    """
                    INSERT INTO user_stats (user_id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET data = EXCLUDED.data
                    """,
                    (uid, json.dumps(data))
                )
        conn.commit()


# =====================
# ACCESS / BLOCK
# =====================
def load_access():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT user_id, data FROM access")
            users = {uid: data for uid, data in c.fetchall()}

            c.execute("SELECT user_id FROM blocked")
            blocked = [uid for (uid,) in c.fetchall()]

            return {"users": users, "blocked": blocked}


def save_access(data):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM access")
            c.execute("DELETE FROM blocked")

            for uid, udata in data["users"].items():
                c.execute(
                    "INSERT INTO access (user_id, data) VALUES (%s, %s)",
                    (uid, json.dumps(udata))
                )

            for uid in data["blocked"]:
                c.execute("INSERT INTO blocked (user_id) VALUES (%s)", (uid,))
        conn.commit()


# =====================
# AUDIT
# =====================
def audit_log(action, admin, target):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO audit (time, action, admin, target)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    datetime.now().strftime("%d-%m-%Y %H:%M"),
                    action,
                    admin,
                    target
                )
            )
        conn.commit()
    return True


def load_audit():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT time, action, admin, target
                FROM audit
                ORDER BY id DESC
                """
            )
            rows = c.fetchall()

    return [
        {
            "time": time,
            "action": action,
            "admin": admin,
            "target": target
        }
        for time, action, admin, target in rows
    ]


# =====================
# HELPERS
# =====================
def new_order(user, items, user_id=None):
    return {
        "id": str(datetime.now().timestamp()),
        "user": user,
        "user_id": user_id,
        "items": items,
        "total": 0,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M")
    }


def calc_total(items, prices):
    return sum(items[i] * prices.get(i, 0) for i in items)

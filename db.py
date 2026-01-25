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

        # 🔥 Drop gamle tabeller (forkert struktur)
        cur.execute("DROP TABLE IF EXISTS sessions CASCADE")
        cur.execute("DROP TABLE IF EXISTS access CASCADE")
        cur.execute("DROP TABLE IF EXISTS lager CASCADE")
        cur.execute("DROP TABLE IF EXISTS prices CASCADE")
        cur.execute("DROP TABLE IF EXISTS user_stats CASCADE")
        cur.execute("DROP TABLE IF EXISTS audit CASCADE")
        cur.execute("DROP TABLE IF EXISTS meta CASCADE")

        # meta
        cur.execute("""
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # sessions – én række med hele datastrukturen
        cur.execute("""
        CREATE TABLE sessions (
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL
        )
        """)

        # access
        cur.execute("""
        CREATE TABLE access (
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL
        )
        """)

        # lager
        cur.execute("""
        CREATE TABLE lager (
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL
        )
        """)

        # prices
        cur.execute("""
        CREATE TABLE prices (
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL
        )
        """)

        # user stats
        cur.execute("""
        CREATE TABLE user_stats (
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL
        )
        """)

        # audit log
        cur.execute("""
        CREATE TABLE audit (
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL
        )
        """)

        # default meta
        cur.execute("""
        INSERT INTO meta (key, value)
        VALUES ('current', NULL)
        """)

        # default rows
        cur.execute(
            "INSERT INTO sessions (data) VALUES (%s)",
            (json.dumps({"current": None, "sessions": {}}),)
        )

        cur.execute(
            "INSERT INTO access (data) VALUES (%s)",
            (json.dumps({"users": {}, "blocked": []}),)
        )

        cur.execute(
            "INSERT INTO lager (data) VALUES (%s)",
            (json.dumps({}),)
        )

        cur.execute(
            "INSERT INTO prices (data) VALUES (%s)",
            (json.dumps({}),)
        )

        cur.execute(
            "INSERT INTO user_stats (data) VALUES (%s)",
            (json.dumps({}),)
        )

        conn.commit()





# =====================
# SESSIONS FUCK AEJJEJEADADAERTGGG
# =====================

def load_sessions():
    with get_conn() as conn:
        cur = conn.cursor()

        # hent current session navn
        cur.execute("SELECT value FROM meta WHERE key='current'")
        row = cur.fetchone()
        current = row[0] if row else None

        # hent seneste sessions-data
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
        cur = conn.cursor()

        # hent seneste access-data
        cur.execute("SELECT data FROM access ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()

        if row and row[0]:
            return row[0]
        else:
            return {
                "users": {},
                "blocked": []
            }



def save_access(data):
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO access (data) VALUES (%s)",
            (json.dumps(data),)
        )

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

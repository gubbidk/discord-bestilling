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

        # =====================
        # TABELLER
        # =====================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        for table in ["sessions", "access", "lager", "prices", "user_stats", "audit"]:
            cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id SERIAL PRIMARY KEY,
                data JSONB NOT NULL
            )
            """)

        # =====================
        # META
        # =====================
        cur.execute("""
        INSERT INTO meta (key, value)
        VALUES ('current', NULL)
        ON CONFLICT (key) DO NOTHING
        """)

        # =====================
        # SESSIONS (kun hvis tom)
        # =====================
        cur.execute("SELECT COUNT(*) FROM sessions")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO sessions (data) VALUES (%s)",
                (json.dumps({"current": None, "sessions": {}}),)
            )

        # =====================
        # ACCESS (kun hvis tom)
        # =====================
        cur.execute("SELECT COUNT(*) FROM access")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO access (data) VALUES (%s)",
                (json.dumps({"users": {}, "blocked": []}),)
            )

        # =====================
        # 🔫 LAGER (kun hvis tom)
        # =====================
        cur.execute("SELECT COUNT(*) FROM lager")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO lager (data) VALUES (%s)",
                (json.dumps({
                    "SNS": 20,
                    "9mm": 20,
                    "vintage": 10,
                    "ceramic": 10,
                    "xm3": 10,
                    "deagle": 10,
                    "Pump": 10,
                    "veste": 200
                }),)
            )

        # =====================
        # 💰 PRISER (kun hvis tom)
        # =====================
        cur.execute("SELECT COUNT(*) FROM prices")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO prices (data) VALUES (%s)",
                (json.dumps({
                    "SNS": 500000,
                    "9mm": 800000,
                    "vintage": 950000,
                    "ceramic": 950000,
                    "xm3": 1500000,
                    "deagle": 1700000,
                    "Pump": 2550000,
                    "veste": 350000
                }),)
            )

        # =====================
        # USER STATS (kun hvis tom)
        # =====================
        cur.execute("SELECT COUNT(*) FROM user_stats")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO user_stats (data) VALUES (%s)",
                (json.dumps({}),)
            )

        # =====================
        # AUDIT (kun hvis tom)
        # =====================
        cur.execute("SELECT COUNT(*) FROM audit")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO audit (data) VALUES (%s)",
                (json.dumps([]),)
            )

        conn.commit()
        print("✅ init_db() OK – data bevares")


# =====================
# SESSIONS
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
            data = {"current": None, "sessions": {}}

        data["current"] = current
        return data


def save_sessions(data):
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO sessions (data) VALUES (%s)",
            (json.dumps(data),)
        )

        cur.execute(
            """
            INSERT INTO meta (key, value)
            VALUES ('current', %s)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value
            """,
            (data.get("current"),)
        )

        conn.commit()


# =====================
# LAGER & PRICES
# =====================
def load_lager():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM lager ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {}


def load_prices():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM prices ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {}


# =====================
# USER STATS
# =====================
def load_user_stats():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM user_stats ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {}


def save_user_stats(stats):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_stats (data) VALUES (%s)",
            (json.dumps(stats),)
        )
        conn.commit()


# =====================
# ACCESS / BLOCK
# =====================
def load_access():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM access ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()

        if row and row[0]:
            return row[0]
        else:
            return {"users": {}, "blocked": []}


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
        cur = conn.cursor()

        cur.execute("SELECT data FROM audit ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        events = row[0] if row else []

        events.append({
            "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
            "action": action,
            "admin": admin,
            "target": target
        })

        cur.execute(
            "INSERT INTO audit (data) VALUES (%s)",
            (json.dumps(events),)
        )
        conn.commit()


def load_audit():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data FROM audit ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else []

def reset_all_stats():
    with get_conn() as conn:
        cur = conn.cursor()

        # Slet alle stats
        cur.execute("DELETE FROM user_stats")

        # Opret tom stats igen
        cur.execute(
            "INSERT INTO user_stats (data) VALUES (%s)",
            (json.dumps({}),)
        )

        conn.commit()


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

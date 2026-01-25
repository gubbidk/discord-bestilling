import os
import json
import psycopg2
from datetime import datetime
from psycopg2.pool import SimpleConnectionPool

# =====================
# CONFIG
# =====================
DATABASE_URL = os.getenv("DATABASE_URL")

# 🔥 GLOBAL CONNECTION POOL
pool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL,
    sslmode="require"
)

# =====================
# CONNECTION HELPERS
# =====================
def get_conn():
    return pool.getconn()

def release_conn(conn):
    pool.putconn(conn)

# =====================
# INIT (KØRES KUN ÉN GANG)
# =====================
def init_db():
    conn = get_conn()
    try:
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
        print("✅ init_db() OK – database klar og data bevaret")

    finally:
        release_conn(conn)

# =====================
# SESSIONS
# =====================
def load_sessions():
    conn = get_conn()
    try:
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

    finally:
        release_conn(conn)

def save_sessions(data):
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO sessions (data) VALUES (%s)",
            (json.dumps(data),)
        )

        cur.execute("""
            INSERT INTO meta (key, value)
            VALUES ('current', %s)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value
        """, (data.get("current"),))

        conn.commit()

    finally:
        release_conn(conn)

# =====================
# LAGER & PRICES
# =====================
def load_lager():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM lager ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {}
    finally:
        release_conn(conn)

def load_prices():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM prices ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {}
    finally:
        release_conn(conn)

# =====================
# USER STATS
# =====================
def load_user_stats():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM user_stats ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {}
    finally:
        release_conn(conn)

def save_user_stats(stats):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_stats (data) VALUES (%s)",
            (json.dumps(stats),)
        )
        conn.commit()
    finally:
        release_conn(conn)

def reset_all_stats():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_stats")
        cur.execute(
            "INSERT INTO user_stats (data) VALUES (%s)",
            (json.dumps({}),)
        )
        conn.commit()
    finally:
        release_conn(conn)

# =====================
# ACCESS / BLOCK
# =====================
def load_access():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM access ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else {"users": {}, "blocked": []}
    finally:
        release_conn(conn)

def save_access(data):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO access (data) VALUES (%s)",
            (json.dumps(data),)
        )
        conn.commit()
    finally:
        release_conn(conn)

# =====================
# AUDIT
# =====================
def audit_log(action, admin, target):
    conn = get_conn()
    try:
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

    finally:
        release_conn(conn)

def load_audit():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM audit ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else []
    finally:
        release_conn(conn)

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

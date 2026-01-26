import os
import json
import psycopg2
import time
from datetime import datetime
from psycopg2.pool import SimpleConnectionPool

# =====================
# CONFIG
# =====================
DATABASE_URL = os.getenv("DATABASE_URL")

pool = None

def create_pool():
    global pool
    pool = SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        dsn=DATABASE_URL,
        sslmode="require",
        connect_timeout=5
    )
    print("✅ DB pool oprettet")

create_pool()

# =====================
# CONNECTION HELPERS (SIKKER)
# =====================
def get_conn():
    global pool

    for _ in range(3):  # prøv 3 gange
        try:
            conn = pool.getconn()
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError:
            print("♻️ DB connection død – prøver igen...")
            time.sleep(0.2)

        except Exception:
            print("♻️ DB pool fejl – genskaber pool...")
            create_pool()
            time.sleep(0.2)

    raise Exception("❌ Kunne ikke oprette database-forbindelse")


def release_conn(conn):
    try:
        pool.putconn(conn)
    except Exception:
        pass  # ignorer døde forbindelser

# =====================
# INIT
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
        # SESSIONS
        # =====================
        cur.execute("SELECT COUNT(*) FROM sessions")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO sessions (data) VALUES (%s)",
                (json.dumps({"current": None, "sessions": {}}),)
            )

        # =====================
        # ACCESS
        # =====================
        cur.execute("SELECT COUNT(*) FROM access")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO access (data) VALUES (%s)",
                (json.dumps({"users": {}, "blocked": []}),)
            )

        # =====================
        # 🔫 LAGER
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
        # 💰 PRISER
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
        # USER STATS
        # =====================
        cur.execute("SELECT COUNT(*) FROM user_stats")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO user_stats (data) VALUES (%s)",
                (json.dumps({}),)
            )

        # =====================
        # AUDIT
        # =====================
        cur.execute("SELECT COUNT(*) FROM audit")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO audit (data) VALUES (%s)",
                (json.dumps([]),)
            )

        conn.commit()
        print("✅ init_db() OK – database klar")

    finally:
        release_conn(conn)

# =====================
# GENERIC LOADERS (SIKRE)
# =====================
def _load_latest(table, default):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT data FROM {table} ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row and row[0] else default
    finally:
        release_conn(conn)


def _insert(table, data):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"INSERT INTO {table} (data) VALUES (%s)", (json.dumps(data),))
        conn.commit()
    finally:
        release_conn(conn)

# =====================
# API FUNKTIONER
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

        data = row[0] if row and row[0] else {"current": None, "sessions": {}}
        data["current"] = current
        return data
    finally:
        release_conn(conn)


def save_sessions(data):
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute("INSERT INTO sessions (data) VALUES (%s)", (json.dumps(data),))

        cur.execute("""
            INSERT INTO meta (key, value)
            VALUES ('current', %s)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value
        """, (data.get("current"),))

        conn.commit()
    finally:
        release_conn(conn)


def load_lager():
    return _load_latest("lager", {})


def load_prices():
    return _load_latest("prices", {})


def load_user_stats():
    return _load_latest("user_stats", {})


def save_user_stats(stats):
    _insert("user_stats", stats)


def reset_all_stats():
    _insert("user_stats", {})


def load_access():
    return _load_latest("access", {"users": {}, "blocked": []})


def save_access(data):
    _insert("access", data)


def audit_log(action, admin, target):
    events = load_audit()

    events.append({
        "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "action": action,
        "admin": admin,
        "target": target
    })

    _insert("audit", events)


def load_audit():
    return _load_latest("audit", [])

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

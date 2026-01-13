import sqlite3
from pathlib import Path
from db import get_conn
DB_PATH = Path("data.db")

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        c = conn.cursor()

        # Lager
        c.execute("""
        CREATE TABLE IF NOT EXISTS lager (
            item TEXT PRIMARY KEY,
            amount INTEGER NOT NULL
        )
        """)

        # Priser
        c.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            item TEXT PRIMARY KEY,
            price INTEGER NOT NULL
        )
        """)

        # Bruger-statistik
        c.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id TEXT PRIMARY KEY,
            orders INTEGER DEFAULT 0
        )
        """)

        conn.commit()

def get_lager(item):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT amount FROM lager WHERE item=?", (item,))
        row = c.fetchone()
        return row[0] if row else 0

def update_lager(item, delta):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
        INSERT INTO lager (item, amount)
        VALUES (?, ?)
        ON CONFLICT(item)
        DO UPDATE SET amount = amount + ?
        """, (item, delta, delta))
        conn.commit()

def get_price(item):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT price FROM prices WHERE item=?", (item,))
        row = c.fetchone()
        return row[0] if row else None

def increment_orders(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
        INSERT INTO user_stats (user_id, orders)
        VALUES (?, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET orders = orders + 1
        """, (user_id,))
        conn.commit()


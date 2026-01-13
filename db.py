import sqlite3
from pathlib import Path
import os
import json

DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = Path(DATA_DIR) / "data.db"
os.makedirs(DATA_DIR, exist_ok=True)

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        c = conn.cursor()

        # sessions.json
        c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            name TEXT PRIMARY KEY,
            open INTEGER,
            data TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # lager.json
        c.execute("""
        CREATE TABLE IF NOT EXISTS lager (
            item TEXT PRIMARY KEY,
            amount INTEGER
        )
        """)

        # prices.json
        c.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            item TEXT PRIMARY KEY,
            price INTEGER
        )
        """)

        # user_stats.json
        c.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id TEXT PRIMARY KEY,
            data TEXT
        )
        """)

        # access.json
        c.execute("""
        CREATE TABLE IF NOT EXISTS access (
            user_id TEXT PRIMARY KEY,
            data TEXT
        )
        """)

        # blocked users
        c.execute("""
        CREATE TABLE IF NOT EXISTS blocked (
            user_id TEXT PRIMARY KEY
        )
        """)

        # audit.json
        c.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            action TEXT,
            admin TEXT,
            target TEXT
        )
        """)

        conn.commit()

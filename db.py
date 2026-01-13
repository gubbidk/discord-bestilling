import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with get_conn() as conn:
        with conn.cursor() as c:

            c.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value JSONB
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                name TEXT PRIMARY KEY,
                open BOOLEAN,
                data JSONB
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS lager (
                item TEXT PRIMARY KEY,
                amount INTEGER
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                item TEXT PRIMARY KEY,
                price INTEGER
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                data JSONB
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS access (
                user_id TEXT PRIMARY KEY,
                data JSONB
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS blocked (
                user_id TEXT PRIMARY KEY
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id SERIAL PRIMARY KEY,
                time TEXT,
                action TEXT,
                admin TEXT,
                target TEXT
            )
            """)

        conn.commit()

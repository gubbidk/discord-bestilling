import os
import json
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, render_template, request, redirect, session, jsonify
from flask_socketio import SocketIO
from db import init_db, get_conn

init_db()

# =====================
# KONFIG
# =====================
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_ADMIN_ROLE = os.getenv("DISCORD_ADMIN_ROLE")
DISCORD_USER_ROLE = os.getenv("DISCORD_USER_ROLE")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_TOKEN")

OAUTH_REDIRECT = "/auth/callback"

# =====================
# FLASK
# =====================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*")

# =====================
# DB HELPERS
# =====================
def load_sessions():
    with get_conn() as conn:
        with conn.cursor() as c:
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

            return {"current": current, "sessions": sessions}

def save_sessions(data):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM sessions")

            for name, s in data["sessions"].items():
                c.execute(
                    "INSERT INTO sessions (name, open, data) VALUES (%s, %s, %s)",
                    (name, s.get("open", False), json.dumps(s))
                )

            c.execute("""
                INSERT INTO meta (key, value)
                VALUES ('current', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (json.dumps(data.get("current")),))

        conn.commit()

    socketio.emit("update")

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

def load_user_stats():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT user_id, data FROM user_stats")
            return {uid: data for uid, data in c.fetchall()}

def save_user_stats(stats):
    with get_conn() as conn:
        with conn.cursor() as c:
            for uid, data in stats.items():
                c.execute("""
                    INSERT INTO user_stats (user_id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data
                """, (uid, json.dumps(data)))
        conn.commit()

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

def audit_log(action, admin, target):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("""
                INSERT INTO audit (time, action, admin, target)
                VALUES (%s, %s, %s, %s)
            """, (
                datetime.now().strftime("%d-%m-%Y %H:%M"),
                action,
                admin,
                target
            ))
        conn.commit()

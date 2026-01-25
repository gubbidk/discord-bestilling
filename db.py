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
        print("✅ init_db() OK – ingen data slettet")

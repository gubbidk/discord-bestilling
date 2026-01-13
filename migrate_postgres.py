import json
import os
from db import get_conn, init_db

init_db()

DATA_DIR = os.getenv("DATA_DIR", ".")
LAGER_FILE = os.path.join(DATA_DIR, "lager.json")
PRICES_FILE = os.path.join(DATA_DIR, "prices.json")

def migrate_lager():
    if not os.path.exists(LAGER_FILE):
        print("❌ lager.json findes ikke")
        return

    with open(LAGER_FILE, "r", encoding="utf-8") as f:
        lager = json.load(f)

    with get_conn() as conn:
        with conn.cursor() as c:
            for item, amount in lager.items():
                c.execute(
                    """
                    INSERT INTO lager (item, amount)
                    VALUES (%s, %s)
                    ON CONFLICT (item)
                    DO UPDATE SET amount = EXCLUDED.amount
                    """,
                    (item, amount)
                )
        conn.commit()

    print(f"✅ Migreret {len(lager)} varer til lager")

def migrate_prices():
    if not os.path.exists(PRICES_FILE):
        print("❌ prices.json findes ikke")
        return

    with open(PRICES_FILE, "r", encoding="utf-8") as f:
        prices = json.load(f)

    with get_conn() as conn:
        with conn.cursor() as c:
            for item, price in prices.items():
                c.execute(
                    """
                    INSERT INTO prices (item, price)
                    VALUES (%s, %s)
                    ON CONFLICT (item)
                    DO UPDATE SET price = EXCLUDED.price
                    """,
                    (item, price)
                )
        conn.commit()

    print(f"✅ Migreret {len(prices)} priser")

if __name__ == "__main__":
    migrate_lager()
    migrate_prices()

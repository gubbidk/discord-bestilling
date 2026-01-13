import json
from db import get_conn, init_db

init_db()

with open("lager.json") as f:
    lager = json.load(f)

with get_conn() as conn:
    c = conn.cursor()
    for item, amount in lager.items():
        c.execute("INSERT OR REPLACE INTO lager VALUES (?, ?)", (item, amount))
    conn.commit()

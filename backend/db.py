import sqlite3, json, time
from backend.config import settings
def conn():
    c = sqlite3.connect(settings.db_path); c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS transactions(order_id TEXT PRIMARY KEY, cart_id TEXT, amount REAL, currency TEXT, status TEXT, capture_id TEXT, items TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS carts(cart_id TEXT PRIMARY KEY, state TEXT);
    CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, cart_id TEXT, amount REAL, lines TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS lists(id TEXT PRIMARY KEY, name TEXT, request TEXT, budget REAL, priority TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY, product_id TEXT, target_price REAL, base_price REAL, created REAL);
    CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY, list_id TEXT, every_days INTEGER, next_run REAL, last_cart_id TEXT);
    CREATE TABLE IF NOT EXISTS approvals(cart_id TEXT PRIMARY KEY, requester TEXT, approver TEXT, status TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS agent_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id TEXT, agent TEXT, action TEXT, detail TEXT, created REAL);""")
    return c
def log(cart_id, agent, action, detail=""):
    with conn() as c: c.execute("INSERT INTO agent_logs(cart_id,agent,action,detail,created) VALUES(?,?,?,?,?)", (cart_id, agent, action, detail, time.time()))
def save_tx(order_id, cart_id, amount, currency, status, capture_id, items):
    with conn() as c: c.execute("INSERT OR IGNORE INTO transactions VALUES(?,?,?,?,?,?,?,?)", (order_id, cart_id, amount, currency, status, capture_id, json.dumps(items), time.time()))
def get_tx(order_id):
    with conn() as c: r = c.execute("SELECT * FROM transactions WHERE order_id=?", (order_id,)).fetchone()
    return dict(r) if r else None
def list_tx():
    with conn() as c: return [dict(r) for r in c.execute("SELECT * FROM transactions ORDER BY created DESC")]

DEFAULT_RULES = {"auto_limit": 10.0, "approval_limit": 50.0, "max_per_purchase": 500.0, "monthly_cap": 1000.0, "category_caps": {}}
def save_cart(cid, state):
    with conn() as c: c.execute("INSERT OR REPLACE INTO carts VALUES(?,?)", (cid, json.dumps(state)))
def load_cart(cid):
    with conn() as c: r = c.execute("SELECT state FROM carts WHERE cart_id=?", (cid,)).fetchone()
    return json.loads(r["state"]) if r else None
def save_order(oid, cid, amount, lines):
    with conn() as c: c.execute("INSERT OR REPLACE INTO orders VALUES(?,?,?,?)", (oid, cid, amount, json.dumps(lines)))
def get_order(oid):
    with conn() as c: r = c.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone()
    return {**dict(r), "lines": json.loads(r["lines"])} if r else None
def get_rules():
    with conn() as c: r = c.execute("SELECT value FROM settings WHERE key='rules'").fetchone()
    return {**DEFAULT_RULES, **(json.loads(r["value"]) if r else {})}
def set_rules(rules):
    with conn() as c: c.execute("INSERT OR REPLACE INTO settings VALUES('rules',?)", (json.dumps(rules),))
def update_tx_status(capture_id, status):
    with conn() as c: c.execute("UPDATE transactions SET status=? WHERE capture_id=?", (status, capture_id))

def save_list(lid, name, request, budget, priority):
    with conn() as c: c.execute("INSERT OR REPLACE INTO lists VALUES(?,?,?,?,?,?)", (lid, name, request, budget, priority, time.time()))
def get_list(lid):
    with conn() as c: r = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    return dict(r) if r else None
def all_lists():
    with conn() as c: return [dict(r) for r in c.execute("SELECT * FROM lists ORDER BY created DESC")]
def logs_for(cart_id):
    with conn() as c: return [dict(r) for r in c.execute("SELECT agent,action,detail FROM agent_logs WHERE cart_id=? ORDER BY id", (cart_id,))]

def month_context():
    """Spend so far this calendar month (UTC) from COMPLETED payments only, so refunds free up budget."""
    import datetime
    from backend.services import catalogue
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    total, by = 0.0, {}
    for t in list_tx():
        if t["status"] != "COMPLETED" or t["created"] < start: continue
        total += t["amount"]
        for l in json.loads(t["items"]):
            p = catalogue.get(l["id"])
            if p: by[p["category"]] = round(by.get(p["category"], 0) + l["unit_price"] * l["quantity"], 2)
    return {"total": round(total, 2), "by_cat": by}

def _one(sql, a=()):
    with conn() as c: r = c.execute(sql, a).fetchone()
    return dict(r) if r else None
def _all(sql, a=()):
    with conn() as c: return [dict(r) for r in c.execute(sql, a)]
def _run(sql, a=()):
    with conn() as c: c.execute(sql, a)
def add_alert(i, pid, target, base): _run("INSERT INTO alerts VALUES(?,?,?,?,?)", (i, pid, target, base, time.time()))
def list_alerts(): return _all("SELECT * FROM alerts ORDER BY created DESC")
def add_schedule(i, lid, days, nxt): _run("INSERT INTO schedules VALUES(?,?,?,?,NULL)", (i, lid, days, nxt))
def list_schedules(): return _all("SELECT * FROM schedules")
def bump_schedule(i, nxt, cart_id): _run("UPDATE schedules SET next_run=?, last_cart_id=? WHERE id=?", (nxt, cart_id, i))
def request_approval(cid, requester, approver): _run("INSERT OR REPLACE INTO approvals VALUES(?,?,?,'pending',?)", (cid, requester, approver, time.time()))
def get_approval(cid): return _one("SELECT * FROM approvals WHERE cart_id=?", (cid,))
def set_approval(cid, status): _run("UPDATE approvals SET status=? WHERE cart_id=?", (status, cid))

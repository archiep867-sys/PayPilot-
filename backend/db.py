import sqlite3, json, time
from backend.config import settings
def conn():
    c = sqlite3.connect(settings.db_path); c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS transactions(order_id TEXT PRIMARY KEY, cart_id TEXT, amount REAL, currency TEXT, status TEXT, capture_id TEXT, items TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS carts(cart_id TEXT PRIMARY KEY, state TEXT);
    CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, cart_id TEXT, amount REAL, lines TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
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

DEFAULT_RULES = {"auto_limit": 10.0, "approval_limit": 50.0, "max_per_purchase": 500.0}
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

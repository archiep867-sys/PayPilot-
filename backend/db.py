import sqlite3, json, time
from backend.config import settings
def conn():
    c = sqlite3.connect(settings.db_path); c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS transactions(order_id TEXT PRIMARY KEY, cart_id TEXT, amount REAL, currency TEXT, status TEXT, capture_id TEXT, items TEXT, created REAL);
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

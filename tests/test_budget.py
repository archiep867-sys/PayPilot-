import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
from fastapi.testclient import TestClient
from backend import main, db
from backend.services import paypal
DEMO = "10 notebooks, 20 pens, 3 marker sets and decorations. Stay within $100. Prioritize quality."
c = TestClient(main.app)
RESET = {"auto_limit": 10, "approval_limit": 50, "max_per_purchase": 500, "monthly_cap": 1000, "category_caps": {}}
def teardown_function(_): c.put("/api/settings", json=RESET)

def _pay(monkeypatch, oid):
    async def cr(cart_id, lines, total, cur="USD"): return oid
    async def cap(o): return {"status": "COMPLETED", "capture_id": "CAP-" + o, "amount": db.get_order(o)["amount"], "currency": "USD"}
    monkeypatch.setattr(paypal, "create_order", cr); monkeypatch.setattr(paypal, "capture", cap)
    p = c.post("/api/shopping/plan", json={"request": DEMO}).json()
    c.post("/api/payments/create-order", json={"cart_id": p["cart_id"], "approved_amount": p["validation"]["total"]})
    return c.post("/api/payments/capture", json={"order_id": oid}).json(), p

def test_monthly_cap_blocks_after_spending(monkeypatch):
    tx, p = _pay(monkeypatch, "B-1")
    spent = c.get("/api/budget").json()["month_spent"]; assert spent >= tx["amount"]
    c.put("/api/settings", json={**RESET, "monthly_cap": spent + 1})
    r = c.post("/api/shopping/plan", json={"request": DEMO}).json()
    assert r["status"] == "blocked" and "monthly cap" in r["validation"]["reason"]
    assert c.post("/api/payments/create-order", json={"cart_id": r["cart_id"], "approved_amount": r["cart"]["total"]}).status_code == 400

def test_refund_frees_monthly_budget(monkeypatch):
    tx, _ = _pay(monkeypatch, "B-2"); before = c.get("/api/budget").json()["month_spent"]
    async def rf(cap): return {"refund_id": "R", "status": "COMPLETED"}
    monkeypatch.setattr(paypal, "refund", rf)
    c.post("/api/payments/refund", json={"order_id": "B-2"})
    assert round(before - c.get("/api/budget").json()["month_spent"], 2) == round(tx["amount"], 2)

def test_category_budget_blocks():
    c.put("/api/settings", json={**RESET, "category_caps": {"notebook": 0.5}})
    r = c.post("/api/shopping/plan", json={"request": DEMO}).json()
    assert r["status"] == "blocked" and "notebook budget" in r["validation"]["reason"]
    assert c.put("/api/settings", json={**RESET, "category_caps": {"spaceship": 5}}).status_code == 422

def test_swap_suggestions_save_money_with_similar_quality():
    r = c.post("/api/shopping/plan", json={"request": DEMO}).json()
    sw = r["cart"]["swap_suggestions"]
    assert sw and all(s["saves"] > 0 and s["quality_change"] >= -0.5 for s in sw)

def test_why_not_explains_with_scores():
    r = c.post("/api/shopping/plan", json={"request": DEMO}).json()
    alt = r["cart"]["items"][0]["alternatives"][0]
    w = c.get(f"/api/shopping/{r['cart_id']}/why-not/{alt}").json()
    assert "scored" in w["message"] and set(w["scores"]) == {"selected", "considered"}
    assert c.get(f"/api/shopping/{r['cart_id']}/why-not/NOPE").status_code == 404

def test_monthly_phrase_sets_monthly_cap_not_per_purchase():
    r = c.post("/api/settings/propose", json={"text": "never spend more than $200 a month, and snacks under $40 a month"}).json()
    assert r["proposed"]["monthly_cap"] == 200 and r["proposed"]["category_caps"]["snack"] == 40
    assert r["proposed"]["max_per_purchase"] == 500 and r["valid"]

def test_health():
    assert c.get("/api/health").json() == {"ok": True}

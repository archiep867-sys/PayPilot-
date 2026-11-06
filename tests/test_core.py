import pytest, os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
from fastapi.testclient import TestClient
from backend import orchestrator, main, db
from backend.agents import discovery_agent, payment_agent
from backend.services import paypal

DEMO = "I need supplies for a college event. Find 10 notebooks, 20 pens, 3 marker sets and decorations. Stay within $100. Prioritize quality but keep the cost low."

async def test_discovery_parses_demo():
    d = await discovery_agent.run(DEMO)
    q = {r["category"]: r["quantity"] for r in d["requirements"]}
    assert q["notebook"] == 10 and q["pen"] == 20 and q["marker"] == 3 and "decoration" in q
    assert d["budget"] == 100 and d["priority"] == "quality"

async def test_plan_within_budget_and_deterministic():
    a = await orchestrator.plan(DEMO); b = await orchestrator.plan(DEMO)
    assert a["cart"]["total"] <= 100 and a["status"] == "ready"
    assert [i["id"] for i in a["cart"]["items"]] == [i["id"] for i in b["cart"]["items"]]

async def test_budget_too_low_is_reported():
    r = await orchestrator.plan("30 notebooks and 50 pens", overrides={"budget": 5})
    assert r["cart"]["status"] == "over_budget" and r["status"] == "blocked"

async def test_no_products():
    r = await orchestrator.plan("hello there")
    assert r["status"] == "no_requirements"

def test_payment_agent_rejects_unknown_ids_and_recomputes():
    assert not payment_agent.validate([{"id": "FAKE-99", "quantity": 1}], 100)["allowed"]
    v = payment_agent.validate([{"id": "PEN-01", "quantity": 10}], 100)
    assert v["total"] == 2.0 and v["level"] == "auto"
    assert payment_agent.validate([{"id": "DEC-05", "quantity": 6}], 100)["level"] == "explicit"
    assert not payment_agent.validate([{"id": "DEC-05", "quantity": 6}], 10)["allowed"]

async def test_amount_mismatch_and_duplicate_capture(monkeypatch):
    async def fake_create(cart_id, lines, total, cur="USD"): return "ORDER123"
    async def fake_capture(oid): return {"status": "COMPLETED", "capture_id": "CAP1", "amount": db.get_order(oid)["amount"], "currency": "USD"}
    monkeypatch.setattr(paypal, "create_order", fake_create); monkeypatch.setattr(paypal, "capture", fake_capture)
    c = TestClient(main.app); n0 = len(c.get("/api/transactions").json())
    plan = c.post("/api/shopping/plan", json={"request": DEMO}).json()
    cid, total = plan["cart_id"], plan["validation"]["total"]
    assert c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": total - 1}).status_code == 409
    assert c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": total}).json()["order_id"] == "ORDER123"
    first = c.post("/api/payments/capture", json={"order_id": "ORDER123"}).json()
    second = c.post("/api/payments/capture", json={"order_id": "ORDER123"}).json()
    assert first["status"] == "COMPLETED" and second.get("duplicate") and len(c.get("/api/transactions").json()) == n0 + 1


def _planned(c):
    p = c.post("/api/shopping/plan", json={"request": DEMO}).json(); return p["cart_id"], p["validation"]["total"]

def _fake_create(oid):
    async def f(cart_id, lines, total, cur="USD"): return oid
    return f

def test_cart_survives_restart_and_settings_apply():
    c = TestClient(main.app); cid, _ = _planned(c)
    assert db.load_cart(cid)["cart"]["items"]  # persisted in SQLite, not memory
    assert c.put("/api/settings", json={"auto_limit": 500, "approval_limit": 600, "max_per_purchase": 700}).status_code == 200
    assert c.put("/api/settings", json={"auto_limit": 50, "approval_limit": 10, "max_per_purchase": 700}).status_code == 422
    assert c.post("/api/shopping/plan", json={"request": DEMO}).json()["validation"]["level"] == "auto"
    c.put("/api/settings", json={"auto_limit": 10, "approval_limit": 50, "max_per_purchase": 500})

def test_price_change_after_planning_is_blocked(monkeypatch):
    from backend.services import catalogue
    c = TestClient(main.app); cid, total = _planned(c)
    pid = db.load_cart(cid)["cart"]["items"][0]["id"]
    monkeypatch.setitem(catalogue._PRODUCTS, pid, {**catalogue._PRODUCTS[pid], "price": catalogue._PRODUCTS[pid]["price"] + 1})
    assert c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": total}).status_code == 409

def test_failed_capture_saves_nothing(monkeypatch):
    async def bad(oid): raise paypal.PayPalError("declined")
    monkeypatch.setattr(paypal, "create_order", _fake_create("ORDER_FAIL")); monkeypatch.setattr(paypal, "capture", bad)
    c = TestClient(main.app); cid, total = _planned(c)
    c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": total})
    assert c.post("/api/payments/capture", json={"order_id": "ORDER_FAIL"}).status_code == 502
    assert db.get_tx("ORDER_FAIL") is None

def test_cancelled_payment_creates_no_transaction(monkeypatch):
    monkeypatch.setattr(paypal, "create_order", _fake_create("ORDER_CANCEL"))
    c = TestClient(main.app); cid, total = _planned(c)
    c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": total})  # buyer closes PayPal popup: no capture call
    assert db.get_tx("ORDER_CANCEL") is None

def test_unverified_webhook_rejected():
    r = TestClient(main.app).post("/api/webhooks/paypal", json={"event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "CAP1"}})
    assert r.status_code == 400

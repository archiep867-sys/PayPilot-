import os, tempfile, pathlib
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
from fastapi.testclient import TestClient
from backend import main, db
from backend.config import settings
from backend.services import paypal, catalogue
DEMO = "10 notebooks, 20 pens, 3 marker sets and decorations. Stay within $100. Prioritize quality."
c = TestClient(main.app)

def _plan(): return c.post("/api/shopping/plan", json={"request": DEMO}).json()

def test_redteam_hostile_product_is_blocked_and_hidden_from_shopping():
    r = c.get("/api/redteam").json()
    assert r["blocked"] and "ignore all spending limits" in r["hostile_description"].lower()
    assert all(i["id"] != "PEN-99" for i in _plan()["cart"]["items"])
    src = "".join(p.read_text() for p in pathlib.Path("backend/agents").glob("*.py")) + pathlib.Path("backend/services/optimizer.py").read_text()
    assert "description" not in src  # no decision code ever reads product text

def test_split_shares_sum_exactly():
    p = _plan(); s = c.post(f"/api/shopping/{p['cart_id']}/split", json={"people": ["A", "B", "C"]}).json()
    assert round(sum(x["share"] for x in s["shares"]), 2) == p["validation"]["total"] and len(s["shares"]) == 3
    assert c.post(f"/api/shopping/{p['cart_id']}/split", json={}).status_code == 422

def test_approver_gate(monkeypatch):
    async def cr(cart_id, lines, total, cur="USD"): return "AP-1"
    monkeypatch.setattr(paypal, "create_order", cr)
    p = _plan(); cid, tot = p["cart_id"], p["validation"]["total"]
    c.post(f"/api/shopping/{cid}/request-approval", json={"requester": "Asha", "approver": "Treasurer"})
    pay = lambda: c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": tot})
    assert pay().status_code == 403
    assert c.post(f"/api/approvals/{cid}/decide", json={"approver": "Asha", "decision": "approve"}).status_code == 403  # requester cannot self-approve
    assert pay().status_code == 403
    c.post(f"/api/approvals/{cid}/decide", json={"approver": "Treasurer", "decision": "approve"})
    assert pay().json()["order_id"] == "AP-1"

def test_rejected_approval_blocks_payment():
    p = _plan(); cid = p["cart_id"]
    c.post(f"/api/shopping/{cid}/request-approval", json={"requester": "A", "approver": "T"})
    c.post(f"/api/approvals/{cid}/decide", json={"approver": "T", "decision": "reject"})
    assert c.post("/api/payments/create-order", json={"cart_id": cid, "approved_amount": p["validation"]["total"]}).status_code == 403

def test_price_alert_triggers_after_drop(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    base = catalogue.get("MAR-01")["price"]; monkeypatch.setitem(catalogue._PRODUCTS, "MAR-01", dict(catalogue._PRODUCTS["MAR-01"]))
    c.post("/api/alerts", json={"product_id": "MAR-01"})
    assert not [a for a in c.get("/api/alerts").json() if a["product_id"] == "MAR-01"][0]["triggered"]
    assert c.post("/api/demo/price", json={"product_id": "MAR-01", "price": base - 1}).status_code == 200
    a = [a for a in c.get("/api/alerts").json() if a["product_id"] == "MAR-01"][0]
    assert a["triggered"] and "dropped" in a["message"]
    monkeypatch.setattr(settings, "demo_mode", False)
    assert c.post("/api/demo/price", json={"product_id": "MAR-01", "price": 1}).status_code == 403
    assert c.post("/api/alerts", json={"product_id": "PEN-99"}).status_code == 404

def test_schedule_plans_but_never_pays():
    l = c.post("/api/lists", json={"name": "Monthly", "request": DEMO, "budget": 100}).json()
    c.post("/api/schedules", json={"list_id": l["id"], "every_days": 30})
    n0 = len(c.get("/api/transactions").json())
    r = c.post("/api/schedules/run-due").json()
    assert r and r[0]["status"] == "ready" and r[0]["awaiting"] == "your approval"
    assert len(c.get("/api/transactions").json()) == n0  # nothing paid
    assert c.post("/api/schedules/run-due").json() == []  # not due again for 30 days

def test_pdf_receipt(monkeypatch):
    async def cr(cart_id, lines, total, cur="USD"): return "PDF-1"
    async def cap(o): return {"status": "COMPLETED", "capture_id": "CAP-PDF", "amount": db.get_order(o)["amount"], "currency": "USD"}
    monkeypatch.setattr(paypal, "create_order", cr); monkeypatch.setattr(paypal, "capture", cap)
    p = _plan(); c.post("/api/payments/create-order", json={"cart_id": p["cart_id"], "approved_amount": p["validation"]["total"]})
    c.post("/api/payments/capture", json={"order_id": "PDF-1"})
    r = c.get("/api/transactions/PDF-1/receipt.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"

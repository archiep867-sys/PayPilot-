import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend import orchestrator, db
from backend.agents import payment_agent
from backend.services import paypal
from backend.config import settings

app = FastAPI(title="PayPilot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
class Rules(BaseModel):
    auto_limit: float
    approval_limit: float
    max_per_purchase: float

class PlanReq(BaseModel):
    request: str
    budget: float | None = None
    priority: str | None = None
class Reopt(BaseModel):
    request: str
    budget: float | None = None
    priority: str | None = None
class CreateOrder(BaseModel):
    cart_id: str
    approved_amount: float  # exact amount the buyer confirmed in the UI
class Capture(BaseModel):
    order_id: str

@app.get("/api/config")
def config(): return {"paypal_client_id": settings.paypal_id, "currency": settings.currency, "sandbox": True}

@app.post("/api/shopping/plan")
async def plan(r: PlanReq):
    return await orchestrator.plan(r.request, r.budget or 100.0, overrides={"budget": r.budget, "priority": r.priority})

@app.post("/api/shopping/reoptimize")  # what-if: new budget/priority, never pays
async def reopt(r: Reopt):
    return await orchestrator.plan(r.request, r.budget or 100.0, overrides={"budget": r.budget, "priority": r.priority})

@app.get("/api/shopping/{cart_id}")
def get_cart(cart_id: str):
    s = db.load_cart(cart_id)
    if not s: raise HTTPException(404, "Cart not found")
    return s

@app.post("/api/payments/create-order")
async def create_order(r: CreateOrder):
    s = db.load_cart(r.cart_id)
    if not s: raise HTTPException(404, "Cart not found")
    items = [{"id": i["id"], "quantity": i["quantity"]} for i in s["cart"]["items"]]
    v = payment_agent.validate(items, s["request"]["budget"], db.get_rules())  # re-validate from trusted prices
    if not v["allowed"]: raise HTTPException(400, v["reason"])
    if round(r.approved_amount, 2) != v["total"]: raise HTTPException(409, f"Approved amount ${r.approved_amount:.2f} does not match cart total ${v['total']:.2f}")
    if s["order_id"]: return {"order_id": s["order_id"], "reused": True}
    try: oid = await paypal.create_order(r.cart_id, v["lines"], v["total"], settings.currency)
    except paypal.PayPalError as e: db.log(r.cart_id, "Payment", "create_failed", str(e)); raise HTTPException(502, str(e))
    s["order_id"] = oid; db.save_cart(r.cart_id, s); db.save_order(oid, r.cart_id, v["total"], v["lines"])
    db.log(r.cart_id, "Payment", "order_created", oid)
    return {"order_id": oid}

@app.post("/api/payments/capture")
async def capture(r: Capture):
    o = db.get_order(r.order_id)
    if not o: raise HTTPException(404, "Unknown order")
    done = db.get_tx(r.order_id)
    if done: return {**done, "duplicate": True}  # idempotent: no second capture
    try: res = await paypal.capture(r.order_id)
    except paypal.PayPalError as e: db.log(o["cart_id"], "Payment", "capture_failed", str(e)); raise HTTPException(502, str(e))
    if res["status"] != "COMPLETED" or round(res["amount"], 2) != o["amount"]:
        db.log(o["cart_id"], "Payment", "verification_failed", str(res)); raise HTTPException(409, "Payment verification failed")
    db.save_tx(r.order_id, o["cart_id"], res["amount"], res["currency"], res["status"], res["capture_id"], o["lines"])
    db.log(o["cart_id"], "Payment", "captured", res["capture_id"])
    return db.get_tx(r.order_id)

@app.get("/api/transactions")
def transactions(): return db.list_tx()

@app.get("/api/settings")
def get_settings(): return db.get_rules()

@app.put("/api/settings")
def put_settings(r: Rules):
    if not (0 <= r.auto_limit <= r.approval_limit <= r.max_per_purchase):
        raise HTTPException(422, "Limits must satisfy 0 <= auto <= approval <= max per purchase")
    db.set_rules(r.model_dump()); return db.get_rules()

@app.post("/api/webhooks/paypal")
async def webhook(req: Request):
    ev = json.loads(await req.body())
    if not await paypal.verify_webhook(req.headers, ev): raise HTTPException(400, "Webhook signature not verified")
    status = {"PAYMENT.CAPTURE.COMPLETED": "COMPLETED", "PAYMENT.CAPTURE.DENIED": "DENIED",
              "PAYMENT.CAPTURE.REFUNDED": "REFUNDED", "PAYMENT.CAPTURE.REVERSED": "REVERSED"}.get(ev.get("event_type"))
    if status and ev.get("resource", {}).get("id"): db.update_tx_status(ev["resource"]["id"], status)
    return {"ok": True}

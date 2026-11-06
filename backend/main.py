import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse, Response
import time
import uuid
from backend import orchestrator, db, features
from backend.agents import payment_agent
from backend.services import paypal
from backend.config import settings

app = FastAPI(title="PayPilot")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["*"], allow_headers=["*"])
class Rules(BaseModel):
    auto_limit: float
    approval_limit: float
    max_per_purchase: float
    monthly_cap: float = 1000.0
    category_caps: dict[str, float] = {}

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
    ap = db.get_approval(r.cart_id)
    if ap and ap["status"] != "approved": raise HTTPException(403, f"Waiting for {ap['approver']} to approve ({ap['status']})")
    items = [{"id": i["id"], "quantity": i["quantity"]} for i in s["cart"]["items"]]
    v = payment_agent.validate(items, s["request"]["budget"], db.get_rules(), db.month_context())  # re-validate from trusted prices
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
    from backend.services import catalogue
    if r.monthly_cap < 0 or any(v < 0 or k not in catalogue.categories() for k, v in r.category_caps.items()):
        raise HTTPException(422, "Monthly caps must be >= 0 and use known categories")
    db.set_rules(r.model_dump()); return db.get_rules()

@app.post("/api/webhooks/paypal")
async def webhook(req: Request):
    ev = json.loads(await req.body())
    if not await paypal.verify_webhook(req.headers, ev): raise HTTPException(400, "Webhook signature not verified")
    status = {"PAYMENT.CAPTURE.COMPLETED": "COMPLETED", "PAYMENT.CAPTURE.DENIED": "DENIED",
              "PAYMENT.CAPTURE.REFUNDED": "REFUNDED", "PAYMENT.CAPTURE.REVERSED": "REVERSED"}.get(ev.get("event_type"))
    if status and ev.get("resource", {}).get("id"): db.update_tx_status(ev["resource"]["id"], status)
    return {"ok": True}

class ListReq(BaseModel):
    name: str
    request: str
    budget: float | None = None
    priority: str | None = None
class RulesText(BaseModel):
    text: str
class Refund(BaseModel):
    order_id: str

@app.post("/api/shopping/compare")
async def compare(r: PlanReq): return await features.compare(r.request, r.budget)

@app.get("/api/analytics")
def analytics(): return features.analytics()

@app.get("/api/transactions/{order_id}/receipt")
def receipt(order_id: str, format: str = "json"):
    r = features.receipt(order_id)
    if not r: raise HTTPException(404, "Transaction not found")
    return PlainTextResponse(features.receipt_text(r)) if format == "text" else r

@app.post("/api/payments/refund")
async def refund(r: Refund):
    t = db.get_tx(r.order_id)
    if not t: raise HTTPException(404, "Transaction not found")
    if t["status"] != "COMPLETED": raise HTTPException(409, f"Cannot refund a {t['status']} payment")
    try: res = await paypal.refund(t["capture_id"])
    except paypal.PayPalError as e: db.log(t["cart_id"], "Payment", "refund_failed", str(e)); raise HTTPException(502, str(e))
    db.update_tx_status(t["capture_id"], "REFUNDED"); db.log(t["cart_id"], "Payment", "refunded", res["refund_id"])
    return {**res, "order_id": r.order_id}

@app.post("/api/lists")
def save_list(r: ListReq):
    lid = uuid.uuid4().hex[:10]; db.save_list(lid, r.name, r.request, r.budget, r.priority); return db.get_list(lid)

@app.get("/api/lists")
def lists(): return db.all_lists()

@app.post("/api/lists/{list_id}/reorder")  # re-plans with CURRENT prices and rules; never pays
async def reorder(list_id: str):
    l = db.get_list(list_id)
    if not l: raise HTTPException(404, "List not found")
    return await orchestrator.plan(l["request"], l["budget"] or 100.0, overrides={"budget": l["budget"], "priority": l["priority"]})

@app.post("/api/settings/propose")
def propose(r: RulesText): return features.propose_rules(r.text)

@app.get("/api/health")
def health(): return {"ok": True}

@app.get("/api/budget")
def budget(): return features.budget_status()

@app.get("/api/shopping/{cart_id}/why-not/{product_id}")
def why_not(cart_id: str, product_id: str):
    r = features.why_not(cart_id, product_id)
    if not r: raise HTTPException(404, "Cart or product not found")
    return r

class AlertReq(BaseModel):
    product_id: str
    target_price: float | None = None
class ScheduleReq(BaseModel):
    list_id: str
    every_days: int = 30
class ApprovalReq(BaseModel):
    requester: str
    approver: str
class Decide(BaseModel):
    approver: str
    decision: str
class SplitReq(BaseModel):
    people: list[str] | None = None
    n: int | None = None
class DemoPrice(BaseModel):
    product_id: str
    price: float

@app.get("/api/transactions/{order_id}/receipt.pdf")
def receipt_pdf(order_id: str):
    r = features.receipt(order_id)
    if not r: raise HTTPException(404, "Transaction not found")
    return Response(features.receipt_pdf(r), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=paypilot-{order_id}.pdf"})

@app.post("/api/alerts")
def add_alert(r: AlertReq):
    from backend.services import catalogue
    p = catalogue.get(r.product_id)
    if not p or p.get("hidden"): raise HTTPException(404, "Unknown product")
    db.add_alert(uuid.uuid4().hex[:10], r.product_id, r.target_price, p["price"]); return features.alerts_view()

@app.get("/api/alerts")
def alerts(): return features.alerts_view()

@app.post("/api/demo/price")  # only when DEMO_MODE=1: lets you simulate a price drop on camera
def demo_price(r: DemoPrice):
    from backend.services import catalogue
    if not settings.demo_mode: raise HTTPException(403, "Demo mode is off (set DEMO_MODE=1)")
    if not catalogue.set_price(r.product_id, r.price): raise HTTPException(404, "Unknown product")
    return {"ok": True}

@app.post("/api/schedules")
def add_schedule(r: ScheduleReq):
    if not db.get_list(r.list_id): raise HTTPException(404, "List not found")
    if r.every_days < 1: raise HTTPException(422, "every_days must be >= 1")
    db.add_schedule(uuid.uuid4().hex[:10], r.list_id, r.every_days, time.time()); return db.list_schedules()

@app.get("/api/schedules")
def schedules(): return db.list_schedules()

@app.post("/api/schedules/run-due")  # plans due lists and queues carts for approval. It NEVER pays.
async def run_due():
    out = []
    for sc in db.list_schedules():
        if sc["next_run"] > time.time(): continue
        l = db.get_list(sc["list_id"])
        p = await orchestrator.plan(l["request"], l["budget"] or 100.0, overrides={"budget": l["budget"], "priority": l["priority"]})
        db.bump_schedule(sc["id"], time.time() + sc["every_days"] * 86400, p["cart_id"])
        out.append({"schedule_id": sc["id"], "cart_id": p["cart_id"], "status": p["status"], "total": p.get("validation", {}).get("total"), "awaiting": "your approval"})
    return out

@app.post("/api/shopping/{cart_id}/request-approval")
def req_approval(cart_id: str, r: ApprovalReq):
    if not db.load_cart(cart_id): raise HTTPException(404, "Cart not found")
    db.request_approval(cart_id, r.requester, r.approver); return db.get_approval(cart_id)

@app.post("/api/approvals/{cart_id}/decide")  # NOTE: names are labels, no real login yet
def decide(cart_id: str, r: Decide):
    ap = db.get_approval(cart_id)
    if not ap: raise HTTPException(404, "No approval request for this cart")
    if r.approver != ap["approver"]: raise HTTPException(403, "Only the named approver can decide")
    if r.decision not in ("approve", "reject"): raise HTTPException(422, "decision must be approve or reject")
    db.set_approval(cart_id, "approved" if r.decision == "approve" else "rejected"); return db.get_approval(cart_id)

@app.post("/api/shopping/{cart_id}/split")
def split(cart_id: str, r: SplitReq):
    if not (r.people or (r.n and r.n >= 2)): raise HTTPException(422, "Give people names or n >= 2")
    out = features.split(cart_id, r.people, r.n)
    if not out: raise HTTPException(404, "Cart not found or not payable")
    return out

@app.get("/api/redteam")
def redteam(): return features.redteam()

# Serve the built React app from the same origin in production (Docker/Render). Must stay last.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
_dist = Path(__file__).parents[1] / "frontend" / "dist"
if _dist.exists(): app.mount("/", StaticFiles(directory=_dist, html=True), name="web")

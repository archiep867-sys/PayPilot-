import uuid
from backend.agents import discovery_agent, decision_agent, payment_agent
from backend import db

async def plan(text, default_budget=100.0, rules=None, overrides=None):
    cid = uuid.uuid4().hex[:12]; trace = []
    def step(agent, title, detail):
        trace.append({"agent": agent, "title": title, "detail": detail}); db.log(cid, agent, title, detail)
    d = await discovery_agent.run(text, default_budget)
    if overrides: d.update({k: v for k, v in overrides.items() if v is not None})
    step("Discovery", "Requirement understood", f"{len(d['requirements'])} categories, budget ${d['budget']:.2f} (parser: {d['parser']})")
    if not d["requirements"]:
        return {"cart_id": cid, "status": "no_requirements", "trace": trace, "message": "I couldn't find any products in your request. Try e.g. '10 notebooks and 20 pens under $50'."}
    rules = rules or db.get_rules()
    cart = await decision_agent.run(d["requirements"], d["budget"], d["priority"])
    step("Discovery", "Catalogue searched", f"{sum(1 + len(i['alternatives']) for i in cart['items'])} candidate products compared")
    step("Decision", "Budget optimized", f"Total ${cart['total']:.2f}, {cart['downgrades']} downgrade(s), status {cart['status']}")
    v = payment_agent.validate([{"id": i["id"], "quantity": i["quantity"]} for i in cart["items"]], d["budget"], rules, db.month_context()) if cart["items"] else {"allowed": False, "level": "blocked", "reason": "No matching products"}
    step("Payment", "Permission checked", v["reason"])
    db.save_cart(cid, {"cart": cart, "validation": v, "request": d, "order_id": None})
    return {"cart_id": cid, "status": "ready" if v["allowed"] else "blocked", "request": d, "cart": cart, "validation": v, "trace": trace}

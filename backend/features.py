"""Convenience features. All numbers come from code/catalogue, never from the LLM."""
import re, json
from backend import db, orchestrator
from backend.agents import discovery_agent, payment_agent
from backend.services import catalogue, optimizer

async def compare(text, budget=None):
    d = await discovery_agent.run(text, budget or 100.0)
    if budget: d["budget"] = budget
    if not d["requirements"]: return {"status": "no_requirements", "carts": {}}
    pool = {r["category"]: catalogue.search(r["category"]) for r in d["requirements"]}
    carts = {}
    for prio, label in (("cheap", "Cheapest"), ("balanced", "Balanced"), ("quality", "Best quality")):
        c = optimizer.optimize(d["requirements"], pool, d["budget"], prio)
        c["label"] = label; c["avg_quality"] = round(sum(i["quality"] * i["quantity"] for i in c["items"]) / max(1, sum(i["quantity"] for i in c["items"])), 2)
        carts[prio] = c
    order = [d["priority"], "balanced", "cheap"]
    pick = next((p for p in order if carts[p]["status"] == "ok"), None)
    why = (f"{carts[pick]['label']} fits your ${d['budget']:.2f} budget at ${carts[pick]['total']:.2f} (average quality {carts[pick]['avg_quality']}/5)." if pick
           else "None of the three carts fit the budget. Raise the budget or reduce quantities.")
    return {"status": "ok" if pick else "over_budget", "request": d, "carts": carts, "recommended": pick, "reason": why}

def analytics():
    txs = [t for t in db.list_tx() if t["status"] == "COMPLETED"]
    by_cat, saved, spent = {}, 0.0, 0.0
    for t in txs:
        spent += t["amount"]
        for l in json.loads(t["items"]):
            p = catalogue.get(l["id"])
            if not p: continue
            by_cat[p["category"]] = round(by_cat.get(p["category"], 0) + l["unit_price"] * l["quantity"], 2)
            top = max(x["price"] for x in catalogue.by_category(p["category"]))
            saved += (top - l["unit_price"]) * l["quantity"]
    return {"total_spent": round(spent, 2), "orders": len(txs), "by_category": by_cat,
            "saved_vs_priciest": round(saved, 2), "refunded": sum(1 for t in db.list_tx() if t["status"] == "REFUNDED")}

def receipt(order_id):
    t = db.get_tx(order_id)
    if not t: return None
    lines = json.loads(t["items"]); cart = db.load_cart(t["cart_id"]) or {}
    return {"order_id": order_id, "capture_id": t["capture_id"], "status": t["status"], "amount": t["amount"], "currency": t["currency"],
            "items": lines, "reasoning": cart.get("cart", {}).get("explanation", ""), "agent_trace": db.logs_for(t["cart_id"]),
            "note": "PayPal Sandbox demo order from a demo catalogue. No real money moved."}

def receipt_text(r):
    rows = "\n".join(f"  {l['quantity']} x {l['name']} @ ${l['unit_price']:.2f}" for l in r["items"])
    return f"PayPilot receipt\nOrder {r['order_id']} | {r['status']}\n{rows}\nTotal: ${r['amount']:.2f} {r['currency']}\n\nWhy: {r['reasoning']}\n\n{r['note']}\n"

def _num(pats, t):
    for p in pats:
        m = re.search(p, t)
        if m: return float(m.group(1))

def propose_rules(text):
    """Plain English -> PROPOSED limits. Never applied until the user confirms via PUT /api/settings."""
    cur = db.get_rules(); new = {**cur, "category_caps": dict(cur.get("category_caps") or {})}
    for clause in re.split(r"[,;.]| and ", text.lower()):
        if "month" in clause:
            n = _num([r"\$\s*(\d+(?:\.\d+)?)", r"(\d+(?:\.\d+)?)"], clause)
            if n is None: continue
            cat = next((c for c in catalogue.categories() if re.search(rf"\b{c}s?\b", clause)), None)
            if cat: new["category_caps"][cat] = n
            else: new["monthly_cap"] = n
            continue
        a = _num([r"auto\w*\D{0,30}\$?(\d+(?:\.\d+)?)", r"(?:without asking|no approval)\D{0,20}\$?(\d+(?:\.\d+)?)"], clause)
        q = _num([r"(?:ask|approv\w*|confirm\w*)\D{0,30}(?:over|above|more than|beyond|up to)\D{0,4}\$?(\d+(?:\.\d+)?)", r"(?:over|above|more than)\s*\$?(\d+(?:\.\d+)?)\D{0,30}(?:ask|approv|confirm)"], clause)
        m = _num([r"never\D{0,30}\$?(\d+(?:\.\d+)?)", r"(?:max\w*|cap|limit)\D{0,20}\$?(\d+(?:\.\d+)?)"], clause)
        if a is not None: new["auto_limit"] = a
        if q is not None: new["approval_limit"] = q
        if m is not None: new["max_per_purchase"] = m
    ok = 0 <= new["auto_limit"] <= new["approval_limit"] <= new["max_per_purchase"]
    return {"current": cur, "proposed": new, "valid": ok, "changed": new != cur,
            "message": "Review and confirm to apply." if ok else "These limits conflict (auto <= approval <= max). Please rephrase."}

def budget_status():
    r, m = db.get_rules(), db.month_context(); cap = r.get("monthly_cap")
    return {"month_spent": m["total"], "monthly_cap": cap, "month_remaining": None if cap is None else round(cap - m["total"], 2),
            "by_category": {c: {"spent": m["by_cat"].get(c, 0), "cap": v, "remaining": round(v - m["by_cat"].get(c, 0), 2)} for c, v in (r.get("category_caps") or {}).items()}}

def why_not(cart_id, product_id):
    s, alt = db.load_cart(cart_id), catalogue.get(product_id)
    if not s or not alt: return None
    prio = s["cart"]["priority"]; sel = next((i for i in s["cart"]["items"] if i["category"] == alt["category"]), None)
    if not sel: return {"message": "That category is not in this cart."}
    if sel["id"] == product_id: return {"message": "That is the product that was selected."}
    pool = catalogue.by_category(alt["category"]); lo, hi = min(p["price"] for p in pool), max(p["price"] for p in pool)
    sa, sb = optimizer.score(sel, lo, hi, prio), optimizer.score(alt, lo, hi, prio)
    msg = (f"{alt['name']} scored {sb:.2f} against {sel['name']} at {sa:.2f} under the '{prio}' priority. "
           f"Price ${alt['price']:.2f} vs ${sel['price']:.2f}, quality {alt['quality']} vs {sel['quality']}, reliability {alt['reliability']} vs {sel['reliability']}.")
    if sb > sa: msg += " It scored higher on its own, but the cart had to fit your budget, so a cheaper option was used."
    return {"message": msg, "selected": sel["id"], "considered": product_id, "scores": {"selected": round(sa, 3), "considered": round(sb, 3)}}


# ---- price alerts ----
def alerts_view():
    out = []
    for a in db.list_alerts():
        p = catalogue.get(a["product_id"]); cur = p["price"] if p else None
        hit = cur is not None and ((a["target_price"] is not None and cur <= a["target_price"]) or (a["target_price"] is None and cur < a["base_price"]))
        out.append({**a, "name": p["name"] if p else None, "current_price": cur, "triggered": bool(hit),
                    "message": f"{p['name']} dropped from ${a['base_price']:.2f} to ${cur:.2f}. Re-plan your cart to use the new price." if hit else "Watching."})
    return out

# ---- split bill (calculates shares only; it does not collect money) ----
def split(cart_id, people=None, n=None):
    s = db.load_cart(cart_id)
    if not s or not s["validation"].get("allowed"): return None
    names = people or [f"Person {i + 1}" for i in range(n or 2)]
    cents = round(s["validation"]["total"] * 100); base, rem = divmod(cents, len(names))
    shares = [{"name": nm, "share": (base + (1 if i < rem else 0)) / 100} for i, nm in enumerate(names)]
    return {"cart_id": cart_id, "total": s["validation"]["total"], "shares": shares,
            "note": "Shares are calculated only. The single PayPal payment is made by one person."}

# ---- red-team demo ----
def redteam():
    p = catalogue.get("PEN-99"); attack = [{"id": "PEN-99", "quantity": 500}]
    v = payment_agent.validate(attack, 50.0, db.get_rules(), db.month_context())
    return {"product": p["name"], "hostile_description": p["description"], "attack_cart": attack, "user_budget": 50.0,
            "validation": v, "blocked": not v["allowed"],
            "explanation": "No agent or optimizer reads product descriptions. Only the payment agent decides, from catalogue prices and your rules."}

# ---- PDF receipt ----
def receipt_pdf(r):
    import io, textwrap
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    b = io.BytesIO(); c = canvas.Canvas(b, pagesize=A4); y = [800]
    def line(t, size=10, dy=15):
        if y[0] < 60: c.showPage(); y[0] = 800
        c.setFont("Helvetica", size); c.drawString(50, y[0], t); y[0] -= dy
    line("PayPilot receipt", 18, 28); line(f"Order {r['order_id']}  |  {r['status']}"); line(f"Capture {r['capture_id']}", dy=22)
    for l in r["items"]: line(f"{l['quantity']} x {l['name']} @ ${l['unit_price']:.2f}")
    line(f"Total: ${r['amount']:.2f} {r['currency']}", 12, 24)
    line("Why the agent chose this", 11)
    for w in textwrap.wrap(r["reasoning"] or "n/a", 95): line(w)
    line("Agent trace", 11, 20)
    for t in r["agent_trace"]: line(f"{t['agent']}: {t['action']} {t['detail'][:70]}")
    line(r["note"], 9, 20); c.save(); return b.getvalue()

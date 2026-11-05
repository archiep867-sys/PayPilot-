"""Agent 3: independent validation. Never trusts client/LLM totals or prices; cannot edit the cart."""
from backend.services import catalogue
DEFAULT_RULES = {"auto_limit": 10.0, "approval_limit": 50.0, "max_per_purchase": 500.0}

def validate(items, budget, rules=None):
    """items: [{id, quantity}] -> recomputed total from catalogue + permission level."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    total, lines = 0.0, []
    for it in items:
        p = catalogue.get(it.get("id"))
        if not p: return {"allowed": False, "reason": f"Unknown product id {it.get('id')!r}", "level": "blocked"}
        q = int(it.get("quantity", 0))
        if q <= 0: return {"allowed": False, "reason": "Invalid quantity", "level": "blocked"}
        total += p["price"] * q; lines.append({"id": p["id"], "name": p["name"], "quantity": q, "unit_price": p["price"]})
    total = round(total, 2)
    if not lines: return {"allowed": False, "reason": "Cart is empty", "level": "blocked"}
    if total > budget: return {"allowed": False, "reason": f"Total ${total:.2f} exceeds budget ${budget:.2f}", "level": "blocked", "total": total}
    if total > rules["max_per_purchase"]: return {"allowed": False, "reason": "Exceeds per-purchase spending limit", "level": "blocked", "total": total}
    level = "auto" if total <= rules["auto_limit"] else ("approval" if total <= rules["approval_limit"] else "explicit")
    return {"allowed": True, "level": level, "total": total, "lines": lines, "currency": "USD",
            "reason": {"auto": "Within auto limit", "approval": "Needs your approval", "explicit": "Needs explicit confirmation of the exact amount"}[level]}

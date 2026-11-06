"""Agent 3: independent validation. Never trusts client/LLM totals or prices; cannot edit the cart."""
from backend.services import catalogue
DEFAULT_RULES = {"auto_limit": 10.0, "approval_limit": 50.0, "max_per_purchase": 500.0, "monthly_cap": 1000.0, "category_caps": {}}

def _block(reason, total=None):
    return {"allowed": False, "reason": reason, "level": "blocked", **({"total": total} if total is not None else {})}

def validate(items, budget, rules=None, month=None):
    """items: [{id, quantity}] -> recomputed total from catalogue + permission level.
    month: {"total": spent this month, "by_cat": {...}} from completed (non-refunded) payments."""
    rules = {**DEFAULT_RULES, **(rules or {})}; month = month or {"total": 0.0, "by_cat": {}}
    total, lines, by_cat = 0.0, [], {}
    for it in items:
        p = catalogue.get(it.get("id"))
        if not p: return _block(f"Unknown product id {it.get('id')!r}")
        q = int(it.get("quantity", 0))
        if q <= 0: return _block("Invalid quantity")
        total += p["price"] * q; by_cat[p["category"]] = by_cat.get(p["category"], 0) + p["price"] * q
        lines.append({"id": p["id"], "name": p["name"], "quantity": q, "unit_price": p["price"]})
    total = round(total, 2)
    if not lines: return _block("Cart is empty")
    if total > budget: return _block(f"Total ${total:.2f} exceeds budget ${budget:.2f}", total)
    if total > rules["max_per_purchase"]: return _block("Exceeds per-purchase spending limit", total)
    cap = rules.get("monthly_cap")
    if cap is not None and month["total"] + total > cap:
        return _block(f"Would exceed your monthly cap: ${month['total']:.2f} spent + ${total:.2f} > ${cap:.2f}", total)
    for cat, ccap in (rules.get("category_caps") or {}).items():
        if month["by_cat"].get(cat, 0) + by_cat.get(cat, 0) > ccap:
            return _block(f"Would exceed your monthly {cat} budget of ${ccap:.2f}", total)
    level = "auto" if total <= rules["auto_limit"] else ("approval" if total <= rules["approval_limit"] else "explicit")
    return {"allowed": True, "level": level, "total": total, "lines": lines, "currency": "USD", "month_after": round(month["total"] + total, 2),
            "reason": {"auto": "Within auto limit", "approval": "Needs your approval", "explicit": "Needs explicit confirmation of the exact amount"}[level]}

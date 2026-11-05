"""Deterministic budget optimizer. The LLM never computes totals."""
W = {"balanced": (0.55, 0.25, 0.20), "quality": (0.25, 0.50, 0.25), "cheap": (0.80, 0.10, 0.10)}

def score(p, lo, hi, priority):
    wp, wq, wr = W.get(priority, W["balanced"])
    price = 1.0 if hi == lo else (hi - p["price"]) / (hi - lo)
    return wp * price + wq * (p["quality"] / 5) + wr * p["reliability"]

def optimize(requirements, catalogue_by_cat, budget, priority="balanced"):
    """requirements: [{category, quantity}]. Returns dict with items, total, status."""
    ranked = {}
    for r in requirements:
        cands = catalogue_by_cat.get(r["category"], [])
        if not cands: continue
        lo, hi = min(c["price"] for c in cands), max(c["price"] for c in cands)
        ranked[r["category"]] = sorted(cands, key=lambda c: (-score(c, lo, hi, priority), c["price"], c["id"]))
    qty = {r["category"]: r["quantity"] for r in requirements if r["category"] in ranked}
    pick = {c: 0 for c in ranked}  # index into ranked list
    total = lambda: round(sum(ranked[c][pick[c]]["price"] * qty[c] for c in ranked), 2)
    swaps = 0
    while total() > budget:
        best = None
        for c in ranked:
            cur = ranked[c][pick[c]]
            for j, alt in enumerate(ranked[c]):
                if alt["price"] < cur["price"]:
                    saved = (cur["price"] - alt["price"]) * qty[c]
                    loss = (ranked[c].index(cur) and 0) + (j - pick[c])  # rank drop
                    key = loss / saved
                    if best is None or key < best[0]: best = (key, c, j)
        if not best: break
        pick[best[1]] = best[2]; swaps += 1
    items = [{**ranked[c][pick[c]], "quantity": qty[c], "line_total": round(ranked[c][pick[c]]["price"] * qty[c], 2),
              "alternatives": [a["id"] for a in ranked[c] if a["id"] != ranked[c][pick[c]]["id"]][:2]} for c in ranked]
    t = total()
    missing = [r["category"] for r in requirements if r["category"] not in ranked]
    status = "over_budget" if t > budget else ("no_products" if not items else "ok")
    return {"items": items, "total": t, "budget": budget, "remaining": round(budget - t, 2),
            "status": status, "downgrades": swaps, "missing_categories": missing, "priority": priority}

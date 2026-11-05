"""Agent 1: natural language -> structured requirements (LLM with rule-based fallback)."""
import re
from backend.services import ai, catalogue
SYN = {"notebook": "notebook", "pen": "pen", "marker": "marker", "decoration": "decoration",
       "decor": "decoration", "snack": "snack", "balloon": "decoration", "chip": "snack", "cookie": "snack"}

def _rule_parse(text, default_budget):
    t = text.lower(); reqs = {}
    for m in re.finditer(r"(\d+)\s+(?:packs?\s+of\s+|sets?\s+of\s+|boxes\s+of\s+)?([a-z]+)", t):
        word = m.group(2).rstrip("s")
        for k, cat in SYN.items():
            if word.startswith(k): reqs[cat] = reqs.get(cat, 0) + int(m.group(1)); break
    for k, cat in SYN.items():  # mentioned without a number -> small default
        if re.search(k, t) and cat not in reqs: reqs[cat] = 2
    b = re.search(r"(?:budget|within|under|stay within|max(?:imum)?)\D{0,12}\$?\s*(\d+(?:\.\d+)?)", t) or re.search(r"\$\s*(\d+(?:\.\d+)?)", t)
    prio = "quality" if "quality" in t else ("cheap" if re.search(r"cheap|lowest|cost", t) and "quality" not in t else "balanced")
    return {"requirements": [{"category": c, "quantity": q} for c, q in reqs.items()],
            "budget": float(b.group(1)) if b else default_budget, "priority": prio, "parser": "rules"}

async def run(text, default_budget=100.0):
    cats = ", ".join(catalogue.categories())
    out = ai.parse_json(await ai.complete(
        f'Extract a shopping request as JSON {{"requirements":[{{"category":str,"quantity":int}}],"budget":number,"priority":"balanced|quality|cheap"}}. '
        f"category must be one of: {cats}. Request: {text}", json_mode=True))
    if out and isinstance(out.get("requirements"), list):
        reqs = [r for r in out["requirements"] if r.get("category") in catalogue.categories() and int(r.get("quantity", 0)) > 0]
        if reqs:
            return {"requirements": [{"category": r["category"], "quantity": int(r["quantity"])} for r in reqs],
                    "budget": float(out.get("budget") or default_budget),
                    "priority": out.get("priority") if out.get("priority") in ("balanced", "quality", "cheap") else "balanced", "parser": "llm"}
    return _rule_parse(text, default_budget)

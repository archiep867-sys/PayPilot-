"""Agent 2: optimizes in Python, LLM (optional) only writes the explanation."""
from backend.services import ai, catalogue, optimizer

async def run(reqs, budget, priority):
    pool = {r["category"]: catalogue.search(r["category"]) for r in reqs}
    cart = optimizer.optimize(reqs, pool, budget, priority)
    lines = [f'{i["quantity"]} x {i["name"]} @ ${i["price"]:.2f} (quality {i["quality"]}/5)' for i in cart["items"]]
    fallback = (f"Selected by weighted score ({cart['priority']} priority) and kept the total at ${cart['total']:.2f} of ${budget:.2f}. "
                + (f"{cart['downgrades']} downgrade(s) were needed to fit the budget. " if cart["downgrades"] else "No downgrades were needed. ")
                + "Items: " + "; ".join(lines))
    text = await ai.complete("Explain in 3 short sentences why this cart was chosen. Use ONLY these facts, do not change numbers: "
                             f"total ${cart['total']}, budget ${budget}, priority {priority}, items: {lines}")
    cart["explanation"] = text or fallback
    return cart

"""Catalogue with demo JSON as the main path. Channel3 is an optional adapter (stub: falls back)."""
import json
from pathlib import Path
from backend.config import settings
_PATH = Path(__file__).parents[2] / "data" / "products.json"
_PRODUCTS = {p["id"]: p for p in json.loads(_PATH.read_text())}

def get(pid): return _PRODUCTS.get(pid)
def by_category(cat):
    return [p for p in _PRODUCTS.values() if p["category"] == cat and not p.get("hidden")]
def categories(): return sorted({p["category"] for p in _PRODUCTS.values() if not p.get("hidden")})
def search(cat):
    # TODO(Channel3): if settings.channel3_key, query API and map results to this schema; on any error fall back.
    return by_category(cat)

def set_price(pid, price):  # demo-mode only (see /api/demo/price)
    if pid in _PRODUCTS: _PRODUCTS[pid] = {**_PRODUCTS[pid], "price": float(price)}; return _PRODUCTS[pid]

"""PayPal Orders v2 (Sandbox). Only called by backend routes after validation + buyer approval, never by the LLM."""
import httpx
from backend.config import settings

class PayPalError(Exception): pass

async def _token(c):
    if not (settings.paypal_id and settings.paypal_secret): raise PayPalError("PayPal credentials not configured")
    r = await c.post(f"{settings.paypal_base}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                     auth=(settings.paypal_id, settings.paypal_secret))
    if r.status_code != 200: raise PayPalError(f"Auth failed: {r.status_code}")
    return r.json()["access_token"]

async def create_order(cart_id, lines, total, currency="USD"):
    items = [{"name": l["name"][:127], "quantity": str(l["quantity"]), "unit_amount": {"currency_code": currency, "value": f'{l["unit_price"]:.2f}'}} for l in lines]
    body = {"intent": "CAPTURE", "purchase_units": [{"reference_id": cart_id, "description": "PayPilot demo order",
            "amount": {"currency_code": currency, "value": f"{total:.2f}", "breakdown": {"item_total": {"currency_code": currency, "value": f"{total:.2f}"}}},
            "items": items}]}
    async with httpx.AsyncClient(timeout=25) as c:
        t = await _token(c)
        r = await c.post(f"{settings.paypal_base}/v2/checkout/orders", json=body,
                         headers={"Authorization": f"Bearer {t}", "PayPal-Request-Id": f"create-{cart_id}"})
    if r.status_code not in (200, 201): raise PayPalError(f"Create order failed: {r.text[:200]}")
    return r.json()["id"]

async def capture(order_id):
    async with httpx.AsyncClient(timeout=25) as c:
        t = await _token(c)
        r = await c.post(f"{settings.paypal_base}/v2/checkout/orders/{order_id}/capture",
                         headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json", "PayPal-Request-Id": f"capture-{order_id}"})
    if r.status_code not in (200, 201): raise PayPalError(f"Capture failed: {r.text[:200]}")
    d = r.json(); cap = d["purchase_units"][0]["payments"]["captures"][0]
    return {"status": d["status"], "capture_id": cap["id"], "amount": float(cap["amount"]["value"]), "currency": cap["amount"]["currency_code"]}

async def verify_webhook(headers, event):
    """Verify a webhook with PayPal's verify-webhook-signature API. False if not configured or invalid."""
    if not settings.paypal_webhook_id: return False
    body = {"auth_algo": headers.get("paypal-auth-algo"), "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"), "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"), "webhook_id": settings.paypal_webhook_id, "webhook_event": event}
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            t = await _token(c)
            r = await c.post(f"{settings.paypal_base}/v1/notifications/verify-webhook-signature", json=body, headers={"Authorization": f"Bearer {t}"})
        return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"
    except Exception:
        return False

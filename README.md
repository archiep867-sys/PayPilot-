# PayPilot — the AI agent that shops, decides and pays (PayPal Sandbox)

Three separate agents + orchestrator:
- **Discovery**: natural language -> structured requirements (Gemini/OpenAI, rule-based fallback)
- **Decision**: deterministic Python optimizer (weighted price/quality/reliability, budget-fit downgrades). LLM only explains.
- **Payment & Compliance**: recomputes totals from trusted catalogue prices, enforces spending rules, never edits the cart.

Safety: the AI never calls PayPal. Backend creates the order only if the buyer-approved amount equals the recomputed total; capture is idempotent and verified against PayPal's response.

## Run
```bash
cp .env.example backend/.env   # fill PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (Sandbox), optional AI key
python -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
pytest                          # 30 tests, no network needed
uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev   # http://localhost:5173
```
Demo catalogue is clearly labelled and settles through one Sandbox merchant account.
License: MIT

## Deploy on Render (free plan)
Push to GitHub, then Render -> New -> Blueprint -> pick this repo (uses `render.yaml` + `Dockerfile`).
Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (Sandbox) and optionally `PAYPAL_WEBHOOK_ID` in the dashboard.
One service serves both the API and the built React app. Free-plan storage is ephemeral, so saved data resets on redeploy.
Webhook URL to register in PayPal: `https://<your-app>.onrender.com/api/webhooks/paypal`.

## More features (backend)
PDF receipts (`/api/transactions/{id}/receipt.pdf`), team approver (`request-approval` / `decide`), split-bill shares, price-drop alerts,
scheduled lists (plan + queue for approval, never auto-pay), and a red-team demo (`/api/redteam`).
Set `DEMO_MODE=1` only when you want to simulate a price drop on camera (`POST /api/demo/price`).
Approver names are labels, not real logins. Authentication is future work.

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
pytest                          # 6 tests, no network needed
uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev   # http://localhost:5173
```
Demo catalogue is clearly labelled and settles through one Sandbox merchant account.
License: MIT

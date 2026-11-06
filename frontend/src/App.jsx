import { useEffect, useState } from "react";
import { PayPalScriptProvider, PayPalButtons } from "@paypal/react-paypal-js";
const DEMO = "I need supplies for a college event. Find 10 notebooks, 20 pens, 3 marker sets and decorations. Stay within $100. Prioritize quality but keep the cost low.";
const api = async (url, body, method = "POST") => { const r = await fetch(url, body ? { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}); const d = await r.json(); if (!r.ok) throw new Error(d.detail || "Request failed"); return d; };
const $ = n => `$${Number(n).toFixed(2)}`;

export default function App() {
  const [cfg, setCfg] = useState(null), [text, setText] = useState(DEMO), [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState(""), [confirmed, setConfirmed] = useState(false), [tx, setTx] = useState(null), [history, setHistory] = useState([]);
  const [rules, setRules] = useState(null), [saved, setSaved] = useState("");
  const saveRules = async () => { try { setRules(await api("/api/settings", rules, "PUT")); setSaved("Spending limits saved"); } catch (e) { setSaved(e.message); } };
  const load = () => api("/api/transactions").then(setHistory).catch(() => {});
  useEffect(() => { api("/api/settings").then(setRules).catch(() => {}); api("/api/config").then(setCfg).catch(() => setErr("Backend not reachable. Start it with: uvicorn backend.main:app --reload")); load(); }, []);
  const run = async (extra = {}) => { setBusy(true); setErr(""); setConfirmed(false); setTx(null); try { setPlan(await api("/api/shopping/plan", { request: text, ...extra })); } catch (e) { setErr(e.message); } setBusy(false); };
  const total = plan?.validation?.total;
  return (
    <main>
      <h1>PayPilot</h1><p className="sub">Tell it what you need. It picks the cart, checks your spending rules, and you approve the payment. Sandbox demo catalogue.</p>
      <div className="box"><textarea value={text} onChange={e => setText(e.target.value)} aria-label="Shopping request" />
        <p><button onClick={() => run()} disabled={busy}>{busy ? "Planning…" : "Plan my purchase"}</button> <button className="alt" onClick={() => run({ budget: (plan?.request?.budget || 100) + 20 })} disabled={!plan || busy}>What if budget +$20?</button> <button className="alt" onClick={() => run({ priority: "cheap" })} disabled={!plan || busy}>Make it cheaper</button></p></div>
      {err && <p className="bad" role="alert">{err}</p>}
      {plan?.message && <p className="warn">{plan.message}</p>}
      {plan?.trace && <div className="row"><div>
        {plan.cart && <div className="box"><h2>Proposed cart</h2>
          <table><thead><tr><th>Item</th><th className="n">Qty</th><th className="n">Unit</th><th className="n">Line</th></tr></thead><tbody>
            {plan.cart.items.map(i => <tr key={i.id}><td>{i.name}</td><td className="n">{i.quantity}</td><td className="n">{$(i.unit_price ?? i.price)}</td><td className="n">{$(i.line_total)}</td></tr>)}
            <tr><th colSpan="3">Total</th><th className="n">{$(plan.cart.total)}</th></tr></tbody></table>
          <p>Budget {$(plan.cart.budget)} · remaining <span className={plan.cart.remaining < 0 ? "bad" : "ok"}>{$(plan.cart.remaining)}</span></p><p>{plan.cart.explanation}</p></div>}
        {plan.status === "ready" && !tx && cfg && <div className="box"><h2>Approve payment</h2>
          <p className={plan.validation.level === "auto" ? "ok" : "warn"}><span className="tag">{plan.validation.reason}.</span> You are authorising exactly {$(total)} {cfg.currency}.</p>
          <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> I approve {$(total)} for this cart</label>
          {confirmed && <PayPalScriptProvider options={{ clientId: cfg.paypal_client_id || "test", currency: cfg.currency }}>
            <PayPalButtons style={{ layout: "vertical" }}
              createOrder={async () => (await api("/api/payments/create-order", { cart_id: plan.cart_id, approved_amount: total })).order_id}
              onApprove={async d => { try { setTx(await api("/api/payments/capture", { order_id: d.orderID })); load(); } catch (e) { setErr(e.message); } }}
              onCancel={() => setErr("Payment cancelled. Nothing was charged.")} onError={() => setErr("PayPal reported an error. Nothing was charged.")} /></PayPalScriptProvider>}</div>}
        {plan.status === "blocked" && <div className="box"><p className="bad"><span className="tag">Blocked:</span> {plan.validation.reason}. Raise the budget or reduce quantities.</p></div>}
        {tx && <div className="box"><p className="ok"><span className="tag">Payment complete.</span> {$(tx.amount)} captured · order {tx.order_id}</p></div>}
      </div>
      <div className="box"><h2>Agent activity</h2><ul className="trace">{plan.trace.map((t, i) => <li key={i}><b>{t.agent}</b>: {t.title}<small>{t.detail}</small></li>)}</ul></div></div>}
      {rules && <div className="box"><h2>Spending rules</h2>
        {[["auto_limit", "Auto-approve up to"], ["approval_limit", "Ask me up to"], ["max_per_purchase", "Never exceed"]].map(([k, l]) => <p key={k}><label>{l} $ <input type="number" min="0" value={rules[k]} onChange={e => setRules({ ...rules, [k]: Number(e.target.value) })} /></label></p>)}
        <button className="alt" onClick={saveRules}>Save limits</button> <span role="status">{saved}</span></div>}
      <div className="box"><h2>Transactions</h2>{history.length === 0 ? <p>No payments yet. Plan a purchase and approve it to see it here.</p> :
        <table><tbody>{history.map(h => <tr key={h.order_id}><td>{h.order_id}</td><td>{h.status}</td><td className="n">{$(h.amount)}</td></tr>)}</tbody></table>}</div>
    </main>);
}

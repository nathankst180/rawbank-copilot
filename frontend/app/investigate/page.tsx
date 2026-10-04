'use client';
import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ChatResponse, Dossier, getDossier, sendChat } from '@/lib/api';
import { Markdown, TopBar } from '@/components/Shell';

const PROMPTS = [
  'Why was this transaction flagged?',
  "Compare this transaction with the customer's normal behaviour.",
  'What happened in the previous 24 hours?',
  'Was this beneficiary newly added?',
  'Has this beneficiary received money from other customers?',
  'Has this device been used across multiple accounts?',
  'Were there failed logins or recent credential changes?',
  'Is there a velocity anomaly?',
  'Is there an impossible travel or cross-border pattern?',
  'Which rules were triggered?',
  'What evidence supports the fraud hypothesis?',
  'What evidence weakens it?',
  'Could this be a false positive?',
  'Find similar activity.',
  'What should the analyst verify next?',
  'Generate an investigation summary.',
];

interface Msg { role: 'user' | 'assistant'; content: string; meta?: ChatResponse }
type Facts = Record<string, string | number | boolean | null>;

function KV({ facts, keys }: { facts: Facts; keys: [string, string][] }) {
  return (
    <div className="kv">
      {keys.map(([k, label]) => (
        <div key={k}><span>{label}</span>{facts?.[k] === null || facts?.[k] === undefined || facts?.[k] === '' ? '—' : String(facts[k])}</div>
      ))}
    </div>
  );
}

function Context({ d }: { d: Dossier }) {
  const f = d.observed_facts;
  const a = f.alert;
  return (
    <aside className="context">
      <div className="sec">
        <div className="sec-title"><span>Investigation context</span><span className="tag EXACT">EXACT</span></div>
        <div className="mono" style={{ color: 'var(--yellow)', fontSize: '.95rem', fontWeight: 700 }}>{d.transaction_id}</div>
        <div style={{ margin: '6px 0 10px', display: 'flex', gap: 8, alignItems: 'center' }}>
          {a.alert_severity ? <span className={`sev ${a.alert_severity}`}>{String(a.alert_severity)}</span> : <span className="chip">No alert</span>}
          {a.alert_score !== null && <span style={{ fontSize: '.8rem' }}>Score <b>{String(a.alert_score)}</b></span>}
          <span style={{ fontSize: '.75rem', color: 'var(--text2)' }}>{String(a.case_status || '')}</span>
        </div>
        <div className="hyp">{d.hypothesis}</div>
      </div>
      <div className="sec"><div className="sec-title">Transaction</div>
        <KV facts={f.transaction} keys={[['event_timestamp_local', 'Time'], ['channel', 'Channel'], ['amount', 'Amount'], ['currency', 'Currency'], ['amount_usd_equiv', 'USD'], ['direction', 'Direction'], ['transaction_status', 'Status'], ['destination_country', 'Destination']]} /></div>
      <div className="sec"><div className="sec-title">Customer</div>
        <KV facts={f.customer} keys={[['customer_id', 'ID'], ['customer_segment', 'Segment'], ['resident_status', 'Residency'], ['kyc_risk_band', 'KYC risk'], ['relationship_tenure_days', 'Tenure (d)'], ['pep_flag', 'PEP']]} /></div>
      <div className="sec"><div className="sec-title">Device</div>
        <KV facts={f.device} keys={[['device_id', 'ID'], ['device_type', 'Type'], ['device_trusted_flag', 'Trusted'], ['device_accounts_seen_30d', 'Accounts (30d)'], ['vpn_proxy_flag', 'VPN/proxy'], ['ip_risk_score', 'IP risk']]} /></div>
      <div className="sec"><div className="sec-title">Beneficiary</div>
        <KV facts={f.beneficiary} keys={[['beneficiary_id', 'ID'], ['beneficiary_type', 'Type'], ['beneficiary_age_days', 'Age (d)'], ['beneficiary_prior_txn_count', 'Prior txns'], ['beneficiary_distinct_sender_count_30d', 'Senders (30d)']]} /></div>
      <div className="sec"><div className="sec-title"><span>Triggered rules</span><span className="tag EXACT">EXACT</span></div>
        {d.triggered_rules.length ? d.triggered_rules.map(r => <span key={r.code} className="rule" title={r.description}>{r.code}</span>) : <span style={{ fontSize: '.75rem', color: 'var(--text3)' }}>None</span>}</div>
      <div className="sec"><div className="sec-title"><span>Supporting</span><span className="tag CALCULATED">CALCULATED</span></div>
        <ul className="ev sup">{d.supporting_evidence.length ? d.supporting_evidence.map((e, i) => <li key={i}>{e}</li>) : <li>None</li>}</ul></div>
      <div className="sec"><div className="sec-title"><span>Counter-evidence</span><span className="tag CALCULATED">CALCULATED</span></div>
        <ul className="ev ctr">{d.counter_evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
      {d.control_exceptions.length > 0 && <div className="sec"><div className="sec-title">Control exceptions (not fraud proof)</div>
        <ul className="ev">{d.control_exceptions.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
      <div className="sec"><div className="sec-title">Evidence gaps</div>
        <ul className="ev">{d.evidence_gaps.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
    </aside>
  );
}

function Workstation() {
  const params = useSearchParams();
  const txn = params.get('transaction_id');
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [err, setErr] = useState('');
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!txn) return;
    getDossier(txn).then(d => { setDossier(d); setErr(''); }).catch(e => setErr(e.message));
  }, [txn]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs, busy]);

  async function ask(q: string) {
    if (!q.trim() || busy) return;
    const history = msgs.map(m => ({ role: m.role, content: m.content }));
    setMsgs(m => [...m, { role: 'user', content: q }]);
    setInput(''); setBusy(true);
    try {
      const r = await sendChat(q, txn, history);
      setMsgs(m => [...m, { role: 'assistant', content: r.answer, meta: r }]);
    } catch (e) {
      setMsgs(m => [...m, { role: 'assistant', content: `The request failed: ${e instanceof Error ? e.message : 'unknown error'}` }]);
    } finally { setBusy(false); }
  }

  if (!txn) return <div className="home"><div className="err">No transaction selected. Open an investigation from the Command Centre or the home page.</div></div>;
  if (err) return <div className="home"><div className="err">{err}</div></div>;

  return (
    <>
      <TopBar txn={txn} />
      <div className="workstation">
        {dossier ? <Context d={dossier} /> : <aside className="context"><span className="thinking">Loading evidence…</span></aside>}
        <section className="chatcol">
          <div className="messages">
            {msgs.length === 0 && (
              <div className="msg-ai">
                <div className="msg-meta"><span className="tag plain">READY</span></div>
                <Markdown text={`### Investigating ${txn}\nAsk a question or pick one below. Answers separate **observed facts**, **derived metrics**, **triggered rules**, **supporting evidence**, **counter-evidence**, **evidence gaps** and a **recommended action**.`} />
              </div>
            )}
            {msgs.map((m, i) => m.role === 'user'
              ? <div key={i} className="msg-user">{m.content}</div>
              : (
                <div key={i} className="msg-ai">
                  {m.meta && (
                    <div className="msg-meta">
                      {m.meta.provenance.map(p => <span key={p} className={`tag ${p}`}>{p.replace('_', ' ')}</span>)}
                      <span className="tag plain">intent: {m.meta.intent} ({m.meta.router})</span>
                      {!m.meta.llm_used && m.meta.provenance.length > 0 && <span className="tag plain">deterministic answer</span>}
                    </div>
                  )}
                  <Markdown text={m.content} />
                  {m.meta?.guards?.map((g, j) => <div key={j} className="guard">Guard: {g}</div>)}
                  {m.meta && !m.meta.llm_used && m.meta.llm_error && <div className="guard">Groq unavailable: {m.meta.llm_error}</div>}
                  {m.meta && m.meta.sources.length > 0 && (
                    <div className="sources">
                      {m.meta.sources.slice(0, 10).map((s, j) => <span key={j}>[{s.type}] {s.ref}{s.score !== undefined ? ` (d=${s.score})` : ''}</span>)}
                    </div>
                  )}
                </div>
              ))}
            {busy && <div className="thinking">Gathering evidence…</div>}
            <div ref={end} />
          </div>
          <div className="composer">
            <div className="prompts">{PROMPTS.map(p => <button key={p} type="button" className="prompt" onClick={() => ask(p)}>{p}</button>)}</div>
            <form onSubmit={e => { e.preventDefault(); ask(input); }}>
              <input value={input} onChange={e => setInput(e.target.value)} disabled={busy}
                placeholder="Ask about this transaction, or mention a CUS-/DEV-/BEN- ID…" aria-label="Question" maxLength={1000} />
              <button className="btn primary" type="submit" disabled={busy || !input.trim()}>Ask</button>
            </form>
          </div>
        </section>
      </div>
    </>
  );
}

export default function InvestigatePage() {
  return <Suspense fallback={<div className="home thinking">Loading…</div>}><Workstation /></Suspense>;
}

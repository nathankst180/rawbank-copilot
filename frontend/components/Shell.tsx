'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getHealth, Health } from '@/lib/api';

export function TopBar({ txn }: { txn?: string | null }) {
  const [h, setH] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    getHealth().then(setH).catch(() => setDown(true));
    const t = setInterval(() => getHealth().then(x => { setH(x); setDown(false); }).catch(() => setDown(true)), 15000);
    return () => clearInterval(t);
  }, []);
  const cc = process.env.NEXT_PUBLIC_COMMAND_CENTRE_URL || 'http://localhost:3000';
  const llm = h?.llm;
  return (
    <>
      <header className="topbar">
        <Link href="/" className="brand" style={{ textDecoration: 'none' }}>
          <div className="brand-mark">R</div>
          <div>
            <div className="brand-name" style={{ color: 'var(--text)' }}>RAWBANK</div>
            <div className="brand-sub">Sentient Fraud Investigation Copilot</div>
          </div>
        </Link>
        <div className="spacer" />
        {down && <span className="chip warn">Copilot API offline</span>}
        {h && (
          <>
            <span className="chip on">Data: {h.records.toLocaleString()} rows</span>
            <span className={`chip ${h.semantic.status === 'ready' ? 'on' : h.semantic.status === 'building' ? 'warn' : 'off'}`}>
              Semantic: {h.semantic.status}
            </span>
            <span className={`chip ${llm?.key_rejected ? 'warn' : llm?.configured ? 'on' : 'off'}`}
              title={llm?.last_error || llm?.model}>
              Groq: {llm?.key_rejected ? 'key rejected' : llm?.configured ? llm.model : 'not configured'}
            </span>
          </>
        )}
        <a className="btn" href={txn ? `${cc}/transactions/${encodeURIComponent(txn)}` : cc}>
          Back to Command Centre
        </a>
      </header>
      <div className="disclaimer">
        Synthetic academic data. Rules FR-01..FR-20 are workshop rules, not Rawbank&apos;s internal policies. Hypotheses
        are for analyst review; this system never sets CONFIRMED_FRAUD.
      </div>
    </>
  );
}

/** Minimal safe markdown: ### headings, - bullets, **bold**, `code`, _italic_. No raw HTML is ever rendered. */
export function Markdown({ text }: { text: string }) {
  const inline = (s: string, k: string) => {
    const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/g).filter(Boolean);
    return parts.map((p, i) =>
      p.startsWith('**') ? <strong key={k + i}>{p.slice(2, -2)}</strong>
        : p.startsWith('`') ? <code key={k + i}>{p.slice(1, -1)}</code>
          : p.startsWith('_') && p.endsWith('_') && p.length > 2 ? <em key={k + i}>{p.slice(1, -1)}</em>
            : <span key={k + i}>{p}</span>);
  };
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = (i: number) => {
    if (list.length) {
      out.push(<ul key={'u' + i}>{list.map((l, j) => <li key={j}>{inline(l, `l${i}${j}`)}</li>)}</ul>);
      list = [];
    }
  };
  text.split('\n').forEach((raw, i) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*]\s+(.*)/);
    if (bullet) { list.push(bullet[1]); return; }
    flush(i);
    const h = line.match(/^#{1,4}\s+(.*)/);
    if (h) out.push(<h3 key={i}>{h[1]}</h3>);
    else if (line.trim() && !line.startsWith('```')) out.push(<p key={i}>{inline(line, `p${i}`)}</p>);
  });
  flush(9999);
  return <div className="md">{out}</div>;
}

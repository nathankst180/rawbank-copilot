'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getQueue, QueueItem } from '@/lib/api';
import { TopBar } from '@/components/Shell';

export default function Home() {
  const router = useRouter();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [err, setErr] = useState('');
  const [id, setId] = useState('');

  useEffect(() => {
    getQueue().then(setQueue).catch(() => setErr('The Copilot API is not reachable. Start the backend on port 8001.'));
  }, []);

  return (
    <>
      <TopBar />
      <main className="home">
        <h1>Investigate a transaction</h1>
        <p>
          The Copilot interrogates the same synthetic banking environment as the Command Centre. Exact data and calculated
          metrics come from deterministic queries; similar activity comes from semantic retrieval; the language model only
          reasons over that evidence.
        </p>
        <div className="flow">
          <span><b>1</b> INVESTIGATE</span><span><b>2</b> CORRELATE</span><span><b>3</b> EXPLAIN</span>
          <span><b>4</b> RECOMMEND</span><span><b>5</b> ESCALATE</span>
        </div>
        <form className="composer" style={{ border: '1px solid var(--border)', borderRadius: 4 }}
          onSubmit={e => { e.preventDefault(); if (id.trim()) router.push(`/investigate?transaction_id=${encodeURIComponent(id.trim())}`); }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <input value={id} onChange={e => setId(e.target.value)} placeholder="Transaction ID, e.g. TXN-SYN0002128"
              aria-label="Transaction ID" style={{ flex: 1, background: 'var(--black)', border: '1px solid var(--border)', color: 'var(--text)', padding: '10px 12px', borderRadius: 3 }} />
            <button className="btn primary" type="submit">Open investigation</button>
          </div>
        </form>
        <h3 style={{ marginTop: 28, fontSize: '.7rem', letterSpacing: '.12em', color: 'var(--text3)', textTransform: 'uppercase' }}>
          Highest-scoring alerts
        </h3>
        {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        <table className="q">
          <thead><tr><th>Transaction</th><th>Severity</th><th>Score</th><th>Pattern</th><th>Customer</th><th>Channel</th><th>USD</th></tr></thead>
          <tbody>
            {queue.map(q => (
              <tr key={q.transaction_id} style={{ cursor: 'pointer' }}
                onClick={() => router.push(`/investigate?transaction_id=${q.transaction_id}`)}>
                <td className="mono" style={{ color: 'var(--yellow)' }}>{q.transaction_id}</td>
                <td><span className={`sev ${q.severity}`}>{q.severity}</span></td>
                <td>{q.score}</td><td>{q.pattern.replace(/_/g, ' ')}</td><td className="mono">{q.customer_id}</td>
                <td>{q.channel}</td><td>${q.amount_usd.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </main>
    </>
  );
}

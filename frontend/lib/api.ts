/** API client for the Copilot backend (a separate service from the Command Centre API). */
const API = process.env.NEXT_PUBLIC_COPILOT_API_URL || 'http://localhost:8001';
export const COMMAND_CENTRE_URL = process.env.NEXT_PUBLIC_COMMAND_CENTRE_URL || 'http://localhost:3000';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json' } });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      msg = (await res.json()).detail || msg;
    } catch {}
    throw new Error(typeof msg === 'string' ? msg : 'Request failed');
  }
  return res.json();
}

export interface Rule { code: string; description: string; weight: number }
export interface Dossier {
  transaction_id: string;
  alerted: boolean;
  hypothesis: string;
  observed_facts: Record<string, Record<string, string | number | boolean | null>>;
  derived_metrics: Record<string, number | null>;
  triggered_rules: Rule[];
  supporting_evidence: string[];
  counter_evidence: string[];
  control_exceptions: string[];
  evidence_gaps: string[];
  recommended_actions: string[];
  false_positive_likelihood: string;
  false_positive_note: string;
}
export interface ChatResponse {
  answer: string;
  intent: string;
  router: string;
  llm_used: boolean;
  model?: string | null;
  transaction_id: string | null;
  provenance: string[];
  guards: string[];
  sources: { type: string; ref: string; score?: number }[];
  llm_error?: string | null;
  not_found?: string[];
  clarify?: { id: string; name: string }[];
  needs_context?: boolean;
}
export interface Health {
  status: string;
  records: number;
  ground_truth_loaded: boolean;
  semantic: { status: string; model: string; dimensions: number | null; cards: number };
  llm: { configured: boolean; key_rejected?: boolean; model: string; last_error: string | null };
}
export interface QueueItem {
  transaction_id: string;
  severity: string;
  score: number;
  pattern: string;
  customer_id: string;
  channel: string;
  amount_usd: number;
}

export const getDossier = (id: string) => call<Dossier>(`/api/dossier/${encodeURIComponent(id)}`);
export const getQueue = () => call<QueueItem[]>('/api/queue');
export const getHealth = () => call<Health>('/api/health');
export const sendChat = (message: string, transaction_id: string | null, history: { role: string; content: string }[]) =>
  call<ChatResponse>('/api/chat', { method: 'POST', body: JSON.stringify({ message, transaction_id, history }) });

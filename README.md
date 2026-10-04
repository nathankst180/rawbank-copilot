# Rawbank Sentient Fraud Investigation Copilot

> **Academic simulation only.** All data is synthetic. Nothing here is Rawbank's real customer data,
> fraud systems or internal rules. FR-01..FR-20 are workshop rules.

**Use Case 02** of the iTech Pre-Sales Technical Build Assignment. This is a **separate application** from
the [Sentient Command Centre](../rawbank-sentient-command-centre) (Use Case 01): its own repository, backend,
frontend, ports, environment and dataset copy. The two form one platform only through a lightweight handoff:

```
Command Centre (3000)  --  "Investigate with Sentient Copilot"  -->  Copilot (3001)
   transaction page          http://localhost:3001/investigate?transaction_id=TXN-...
```

Copilot flow: **Investigate -> Correlate -> Explain -> Recommend -> Escalate**.

## Architecture - "the LLM is not the database"

```
RAWBANK_SENTIENT_KB.csv  (no ground truth, ever)
   |-- Pandas + RapidFuzz  -> EXACT facts, CALCULATED metrics, entity resolution
   |-- Retrieval cards -> multilingual-e5-small (CPU, 384-d, normalised) -> FAISS IndexFlatL2 -> RETRIEVED similar activity
                         |
                  Context builder (evidence package)
                         |
                Groq openai/gpt-oss-20b  -> AI REASONING (over the package only) -> output guard
```

Every answer carries provenance tags: **EXACT**, **CALCULATED**, **RETRIEVED**, **AI REASONING**.
Embeddings are never used for exact IDs, amounts, timestamps or counts.

| Module | Role |
|---|---|
| `backend/app/store.py` | Loads only `RAWBANK_SENTIENT_KB.csv`; refuses a ground-truth path |
| `backend/app/entities.py` | ID patterns, RapidFuzz names, unknown IDs and ambiguity reported, never guessed |
| `backend/app/investigation.py` | Deterministic dossier: facts, metrics, rules, supporting/counter-evidence, gaps, actions |
| `backend/app/retrieval.py` | E5 + FAISS semantic search over retrieval cards |
| `backend/app/llm.py` | Groq intent routing + synthesis, keyword fallback, output guard |
| `backend/app/chat.py` | Orchestration; deterministic answer when Groq is unavailable |

### Response structure (ruleset section 12)
Observed facts, derived metrics, triggered rules, supporting evidence, counter-evidence, evidence gaps, recommended
analyst action. Wording is hedged ("consistent with possible account takeover"). The system **never sets
`CONFIRMED_FRAUD`**; a guard rewrites definitive-fraud wording and flags any ID in AI text that is not in the data.

### Guardrails
- Unknown IDs: "not found in the dataset"; the LLM is not called.
- Ambiguous names: asks which record was meant.
- Insufficient evidence is stated via the *Evidence gaps* section.
- ATM/POS terminals and merchants are marked as institutional (many accounts/senders is expected).
- Visa Direct / ATM-deposit limit breaches are labelled control exceptions, not fraud proof.
- No Groq key or a rejected key: the app keeps working with a clearly-labelled deterministic answer.

## Run

```bash
# backend (port 8001)
cd backend
pip install -r requirements.txt
cp .env.example .env        # set GROQ_API_KEY (https://console.groq.com/keys). Never commit .env
python -m uvicorn main:app --port 8001

# frontend (port 3001)
cd frontend
npm install
npm run dev
```

First start downloads `intfloat/multilingual-e5-small` and builds the FAISS index (~1 min on CPU); it is cached in
`backend/.cache/`. `GET /api/health` reports data, semantic-index and Groq status (`?check_llm=true` for a live call).

## API
`GET /api/health` - `GET /api/queue` - `GET /api/dossier/{txn}` - `GET /api/resolve?q=` - `POST /api/chat`
`{message, transaction_id?, history[]}`

## Tests
```bash
cd backend && pip install -r requirements-dev.txt && pytest -q
```
Runs without Groq. Covers: dossier vs CSV, the seven sections, hedged wording, unknown/ambiguous entities, no-alert
transactions, diaspora and institutional false-positive context, router coverage, output guard, ground-truth refusal.

## Known limitations
- Groq reasoning requires a valid key; otherwise answers are deterministic.
- The false-positive view is a transparent heuristic, not a probability.
- No authentication; single analyst; synthetic data only.

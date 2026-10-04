"""Rawbank Sentient Fraud Investigation Copilot - API (Use Case 02).
A SEPARATE application from the Command Centre. Synthetic academic data only."""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import chat, llm, retrieval
from app.entities import resolve
from app.investigation import build_dossier
from app.store import kb

load_dotenv()
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    kb()
    llm._chat([{"role": "user", "content": "Reply: ok"}], max_tokens=100)  # validate the Groq key once at startup
    retrieval.start_background()  # E5 + FAISS builds in the background; exact retrieval is available immediately
    yield


app = FastAPI(title="Rawbank Sentient Fraud Investigation Copilot API", version="1.0.0", lifespan=lifespan,
              description="Evidence-grounded investigation over a synthetic banking dataset. Not Rawbank's real data.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3001").split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class Turn(BaseModel):
    role: str
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    transaction_id: str | None = None
    history: list[Turn] = []


@app.get("/api/health")
def health(check_llm: bool = False):
    d = kb()
    out = {"status": "ok", "records": int(len(d)), "data_source": "RAWBANK_SENTIENT_KB.csv",
           "ground_truth_loaded": False, "semantic": retrieval.status(), "llm": llm.llm_state(),
           "disclaimer": "Academic simulation. All data is synthetic; not Rawbank's real data or internal rules."}
    if check_llm:
        out["llm"]["live_check"] = bool(llm._chat([{"role": "user", "content": "Reply: ok"}], max_tokens=100))
        out["llm"]["last_error"] = llm.llm_state()["last_error"]
    return out


@app.get("/api/queue")
def queue(limit: int = Query(12, ge=1, le=50)):
    """Highest-scoring alerts (exact) to start an investigation from."""
    d = kb()
    a = d[d.alert_generated_flag].sort_values(["alert_score", "ts"], ascending=[False, False]).head(limit)
    return [{"transaction_id": r.transaction_id, "severity": r.alert_severity, "score": int(r.alert_score),
             "pattern": r.alert_primary_pattern, "customer_id": r.customer_id, "channel": r.channel,
             "amount_usd": float(r.amount_usd_equiv)} for r in a.itertuples()]


@app.get("/api/dossier/{transaction_id}")
def dossier(transaction_id: str):
    d = build_dossier(transaction_id)
    if d is None:
        raise HTTPException(404, f"Transaction {transaction_id} not found in the dataset")
    return d


@app.get("/api/resolve")
def resolve_entities(q: str = Query(min_length=1, max_length=200)):
    return resolve(q)


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    if req.transaction_id and build_dossier(req.transaction_id) is None:
        raise HTTPException(404, f"Transaction {req.transaction_id} not found in the dataset")
    try:
        return chat.answer(req.message, req.transaction_id, [t.model_dump() for t in req.history])
    except Exception:
        logging.getLogger("copilot").exception("chat failed")
        raise HTTPException(500, "The investigation request failed - see server logs")

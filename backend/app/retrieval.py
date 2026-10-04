"""Semantic retrieval: retrieval cards -> intfloat/multilingual-e5-small (CPU, 384-d, normalised) -> FAISS IndexFlatL2.
Used ONLY for 'find similar activity' style questions. Never for exact IDs, amounts, timestamps or counts
(those come from the Pandas layer). Falls back to 'unavailable' - never silently to something fake."""
import logging
import os
import threading
from pathlib import Path

import numpy as np

from .store import kb

log = logging.getLogger("copilot.retrieval")
CACHE = Path(__file__).resolve().parents[1] / ".cache"
MODEL_NAME = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")

_state = {"status": "idle", "error": None, "index": None, "ids": [], "model": None, "dim": None}
_lock = threading.Lock()


def card_text(r) -> str:
    """Clean natural-language card built from selected CSV fields."""
    bits = [
        f"{r.channel} {str(r.transaction_type).replace('_', ' ').lower()} of {r.amount_usd_equiv:,.0f} USD ({r.direction})",
        f"customer segment {r.customer_segment}, {str(r.resident_status).lower()}",
    ]
    if r.beneficiary_id:
        bits.append(f"to {str(r.beneficiary_type).lower().replace('_', ' ')} beneficiary"
                    + (", newly added" if r.new_beneficiary_flag else ", established"))
    bits.append(("new or untrusted" if (r.new_device_flag or not r.device_trusted_flag) else "trusted") + f" {str(r.device_type).lower().replace('_', ' ')}")
    if r.vpn_proxy_flag:
        bits.append("VPN or proxy")
    if r.is_cross_border:
        bits.append(f"cross-border {r.origin_country} to {r.destination_country}")
    if r.impossible_travel_flag:
        bits.append("impossible travel")
    if r.login_failures_30m and r.login_failures_30m >= 3:
        bits.append(f"{int(r.login_failures_30m)} failed logins")
    if r.txn_count_10m and r.txn_count_10m >= 4:
        bits.append(f"{int(r.txn_count_10m)} transactions in 10 minutes")
    if r.amount_to_median_ratio and r.amount_to_median_ratio >= 5:
        bits.append(f"{r.amount_to_median_ratio:.0f} times the customer median")
    if r.alert_generated_flag:
        bits.append(f"alert {r.alert_severity} pattern {str(r.alert_primary_pattern).replace('_', ' ').lower()}, rules {r.alert_reason_codes}")
    else:
        bits.append("no alert, normal activity")
    return "; ".join(bits)


def _build():
    try:
        from sentence_transformers import SentenceTransformer
        import faiss
        d = kb()
        ids = list(d.transaction_id)
        model = SentenceTransformer(MODEL_NAME, device="cpu")
        CACHE.mkdir(exist_ok=True)
        f = CACHE / "embeddings.npy"
        if f.exists() and np.load(f).shape[0] == len(ids):
            emb = np.load(f)
        else:
            cards = ["passage: " + card_text(r) for r in d.itertuples()]
            emb = model.encode(cards, batch_size=64, normalize_embeddings=True, show_progress_bar=False).astype("float32")
            np.save(f, emb)
        index = faiss.IndexFlatL2(emb.shape[1])
        index.add(emb)
        with _lock:
            _state.update(status="ready", index=index, ids=ids, model=model, dim=emb.shape[1], error=None)
        log.info("semantic index ready: %d cards, dim %d", len(ids), emb.shape[1])
    except Exception as e:  # noqa: BLE001
        log.exception("semantic index failed")
        with _lock:
            _state.update(status="unavailable", error=f"{type(e).__name__}: {e}"[:200])


def start_background():
    with _lock:
        if _state["status"] != "idle":
            return
        _state["status"] = "building"
    threading.Thread(target=_build, daemon=True).start()


def status() -> dict:
    return {"status": _state["status"], "error": _state["error"], "model": MODEL_NAME, "dimensions": _state["dim"],
            "index": "faiss.IndexFlatL2", "cards": len(_state["ids"])}


def similar(query_txn_id: str | None = None, text: str | None = None, k: int = 5):
    """Return [{transaction_id, distance, card}] or None if the index is not ready."""
    if _state["status"] != "ready":
        return None
    d = kb()
    if query_txn_id:
        r = d[d.transaction_id == query_txn_id]
        if r.empty:
            return []
        q = "query: " + card_text(r.iloc[0])
    else:
        q = "query: " + (text or "")
    v = _state["model"].encode([q], normalize_embeddings=True).astype("float32")
    dist, idx = _state["index"].search(v, k + 1)
    out = []
    for dd, ii in zip(dist[0], idx[0]):
        tid = _state["ids"][ii]
        if tid == query_txn_id:
            continue
        rr = d[d.transaction_id == tid].iloc[0]
        out.append({"transaction_id": tid, "distance": round(float(dd), 4), "card": card_text(rr),
                    "alert": bool(rr.alert_generated_flag), "severity": rr.alert_severity or None})
    return out[:k]

"""Copilot tests. They run WITHOUT Groq (LLM disabled) so they verify the deterministic evidence layer
and the guardrails. Run: cd backend && pytest -q"""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

os.environ["GROQ_API_KEY"] = ""  # force the deterministic path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import llm  # noqa: E402
from app.entities import resolve  # noqa: E402
from app.investigation import build_dossier  # noqa: E402
from app.store import csv_path, kb  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
raw = pd.read_csv(csv_path(), keep_default_na=False)
raw["_alert"] = raw.alert_generated_flag.astype(str).str.upper() == "TRUE"


def chat(msg, txn=None):
    r = client.post("/api/chat", json={"message": msg, "transaction_id": txn})
    assert r.status_code == 200, r.text
    return r.json()


def test_ground_truth_never_loaded():
    assert "GROUND_TRUTH" not in csv_path().name.upper()
    assert not any("ground" in c.lower() for c in kb().columns)
    assert client.get("/api/health").json()["ground_truth_loaded"] is False


def test_dossier_matches_csv_exactly():
    r = raw[raw._alert].iloc[3]
    d = build_dossier(r.transaction_id)
    assert d["observed_facts"]["customer"]["customer_id"] == r.customer_id
    assert [x["code"] for x in d["triggered_rules"]] == r.alert_reason_codes.split("|")
    cust = raw[raw.customer_id == r.customer_id]
    assert d["derived_metrics"]["customer_total_txns_in_dataset"] == len(cust)
    assert d["derived_metrics"]["device_distinct_customers_in_dataset"] == raw[raw.device_id == r.device_id].customer_id.nunique()


def test_all_seven_sections_present():
    d = build_dossier(raw[raw._alert].iloc[0].transaction_id)
    for k in ["observed_facts", "derived_metrics", "triggered_rules", "supporting_evidence", "counter_evidence",
              "evidence_gaps", "recommended_actions"]:
        assert k in d and d[k] is not None
    assert d["evidence_gaps"], "must always state what is not known"


def test_hedged_wording_and_no_confirmed_fraud():
    for tid in raw[raw._alert].transaction_id.head(40):
        d = build_dossier(tid)
        assert "consistent with" in d["hypothesis"] and "not a finding of fraud" in d["hypothesis"]
    assert "never sets CONFIRMED_FRAUD" in " ".join(build_dossier(raw[raw._alert].iloc[0].transaction_id)["recommended_actions"])


def test_unknown_transaction_says_not_found():
    r = chat("Tell me about TXN-SYN9999999")
    assert r["not_found"] == ["TXN-SYN9999999"] and r["llm_used"] is False
    assert client.get("/api/dossier/NOPE").status_code == 404
    assert client.post("/api/chat", json={"message": "hi", "transaction_id": "NOPE"}).status_code == 404


def test_no_alert_transaction_is_not_accused():
    t = raw[~raw._alert].iloc[0].transaction_id
    d = build_dossier(t)
    assert d["alerted"] is False and "does not indicate suspicious activity" in d["hypothesis"]
    assert d["false_positive_likelihood"] == "NOT_APPLICABLE"


def test_institutional_terminals_and_merchants_are_flagged_as_expected():
    """Shared ATM/POS devices and merchants legitimately touch many accounts/senders (false-positive challenge)."""
    from app.investigation import entity_summary
    term = raw[raw.device_type.isin(["ATM_TERMINAL", "POS_TERMINAL"])].device_id.iloc[0]
    assert entity_summary("device", term)["institutional_terminal"] is True
    merch = raw[raw.beneficiary_type == "MERCHANT"].beneficiary_id.iloc[0]
    assert entity_summary("beneficiary", merch)["is_merchant"] is True


def test_ambiguous_name_asks_for_clarification():
    r = chat("Show me the customer SYN Retail Customer")
    assert r.get("clarify") and r["llm_used"] is False


def test_false_positive_scenarios_surface_counter_evidence():
    seen = 0
    for tid in raw[raw._alert & (raw.resident_status == "DIASPORA") & (raw.is_cross_border.astype(str).str.upper() == "TRUE")].transaction_id.head(10):
        assert any("Diaspora" in c for c in build_dossier(tid)["counter_evidence"])
        seen += 1
    assert seen > 0


def test_entity_resolution_exact_and_fuzzy():
    assert resolve("check dev-00141")["found"]["device"] == ["DEV-00141"]
    assert resolve("look at CUS-99999")["unknown"] == ["CUS-99999"]
    name = raw.customer_name.iloc[0]
    assert raw.customer_id.iloc[0] in resolve(f"What about {name}?")["found"].get("customer", [])


def test_device_question_uses_exact_aggregates():
    r = chat("Has this device been used across multiple accounts? DEV-00141")
    assert "233" in r["answer"] and "POS_TERMINAL" in r["answer"] and "institutional" in r["answer"].lower()


def test_chat_every_prompt_returns_structured_answer():
    t = raw[raw._alert].iloc[0].transaction_id
    for q in ["Why was this transaction flagged?", "What happened in the previous 24 hours?", "Which rules were triggered?",
              "What evidence weakens it?", "Could this be a false positive?", "What should the analyst verify next?",
              "Generate an investigation summary.", "Is there a velocity anomaly?"]:
        r = chat(q, t)
        assert r["answer"] and r["transaction_id"] == t and "EXACT" in r["provenance"]


def test_no_context_asks_for_one():
    assert chat("Why was this flagged?")["needs_context"] is True


def test_guard_rewrites_definitive_fraud_claims():
    txt, applied = llm.guard("The customer has committed fraud and this is confirmed fraud.")
    assert "committed fraud" not in txt and "confirmed fraud" not in txt.lower() and applied


def test_keyword_router_covers_required_questions():
    assert llm.keyword_intent("Could this be a false positive?") == "false_positive"
    assert llm.keyword_intent("What evidence weakens it?") == "counter"
    assert llm.keyword_intent("Generate an investigation summary.") == "case_summary"
    assert llm.keyword_intent("Find similar activity") == "similar"
    assert llm.keyword_intent("Has this device been used across multiple accounts?") == "device"

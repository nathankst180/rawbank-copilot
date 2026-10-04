"""Orchestration: entity resolution -> intent routing -> exact/calculated evidence -> (semantic retrieval)
-> Groq synthesis (or deterministic composer) -> output guard. Every answer states what came from where."""
import re

from . import llm, retrieval
from .entities import PATTERNS, resolve
from .investigation import build_dossier, entity_summary
from .store import kb

# which dossier parts each intent needs
SECTIONS = {
    "explain_flag": ["triggered_rules", "supporting_evidence", "counter_evidence", "derived_metrics", "evidence_gaps", "recommended_actions"],
    "behaviour_compare": ["derived_metrics", "supporting_evidence", "counter_evidence"],
    "timeline": ["derived_metrics", "related_activity"],
    "beneficiary": ["derived_metrics", "supporting_evidence", "counter_evidence", "evidence_gaps"],
    "network": ["derived_metrics", "related_activity", "counter_evidence"],
    "device": ["derived_metrics", "related_activity", "counter_evidence"],
    "authentication": ["derived_metrics", "supporting_evidence", "evidence_gaps"],
    "velocity": ["derived_metrics", "related_activity", "supporting_evidence"],
    "geography": ["derived_metrics", "supporting_evidence", "counter_evidence"],
    "rules": ["triggered_rules", "supporting_evidence"],
    "support": ["triggered_rules", "supporting_evidence", "derived_metrics"],
    "counter": ["counter_evidence", "control_exceptions", "false_positive_likelihood", "evidence_gaps"],
    "false_positive": ["counter_evidence", "supporting_evidence", "false_positive_likelihood", "false_positive_note", "evidence_gaps"],
    "next_action": ["recommended_actions", "evidence_gaps", "triggered_rules"],
    "case_summary": ["triggered_rules", "supporting_evidence", "counter_evidence", "derived_metrics", "evidence_gaps", "recommended_actions", "false_positive_likelihood"],
    "similar": ["triggered_rules", "supporting_evidence"],
    "stats": [],
}
FACTS = {
    "beneficiary": ["beneficiary"], "network": ["beneficiary", "device"], "device": ["device"],
    "authentication": ["authentication", "device"], "geography": ["geography", "transaction", "device"],
    "behaviour_compare": ["transaction", "customer"], "velocity": ["transaction"], "timeline": ["transaction", "customer"],
}
ID_RE = re.compile(r"\b(?:TXN-[A-Z]*\d+|CUS-\d+|DEV-\d+|BEN-\d+|CASE-\d+)\b")
HEAD = {"triggered_rules": "Triggered rules", "supporting_evidence": "Supporting evidence",
        "counter_evidence": "Counter-evidence", "evidence_gaps": "Evidence gaps",
        "recommended_actions": "Recommended analyst action", "control_exceptions": "Control exceptions (not fraud proof)"}


def _compose(d: dict, intent: str, summaries: list[dict], sim) -> str:
    """Deterministic answer (used when Groq is unavailable). Same evidence, no AI phrasing."""
    L = [f"**{d['hypothesis']}**", ""]
    keys = SECTIONS.get(intent, SECTIONS["explain_flag"])
    if "triggered_rules" in keys and d["triggered_rules"]:
        L += ["### Triggered rules (synthetic workshop rules)"] + [f"- **{r['code']}** {r['description']} (+{r['weight']})" for r in d["triggered_rules"]] + [""]
    if "derived_metrics" in keys:
        m = d["derived_metrics"]
        L += ["### Derived metrics (calculated)"]
        for k, v in m.items():
            if v is not None and (intent not in ("device", "beneficiary", "network") or any(t in k for t in ("device", "beneficiary", "ratio"))):
                L.append(f"- {k.replace('_', ' ')}: {v}")
        L.append("")
    for k in ("supporting_evidence", "counter_evidence", "control_exceptions", "evidence_gaps", "recommended_actions"):
        if k in keys and d.get(k):
            L += [f"### {HEAD[k]}"] + [f"- {x}" for x in d[k]] + [""]
    if "false_positive_likelihood" in keys:
        L += [f"### False-positive view\n- Likelihood (heuristic): **{d['false_positive_likelihood']}**. {d['false_positive_note']}", ""]
    if "related_activity" in keys:
        ra = d["related_activity"]
        L += ["### Related activity (exact)",
              f"- Customer transactions in the prior 24h: {len(ra['customer_last_24h'])}",
              f"- Other customers on this device: {', '.join(ra['device_other_customers']) or 'none'}",
              f"- Other senders to this beneficiary: {', '.join(ra['beneficiary_other_senders']) or 'none'}", ""]
        for x in ra["customer_last_24h"][:6]:
            L.append(f"  - {x['transaction_id']} {x['ts']} {x['channel']} ${x['amount_usd']:,.2f}" + (f" ALERT {x['severity']}" if x["alert"] else ""))
        L.append("")
    for s in summaries:
        L.append(f"### {s['kind'].title()} {s['id']}\n- {s['transactions']} transactions, {s['alerts']} alerts ({s['alert_rate_pct']}%), ${s['total_usd']:,.2f} total")
    if sim:
        L += ["### Similar activity (retrieved semantically; verify exact values in the data)"] + [f"- {x['transaction_id']} (distance {x['distance']}): {x['card']}" for x in sim] + [""]
    L.append("_Deterministic answer: Groq reasoning layer was not used for this response._")
    return "\n".join(L)


def _overall_stats() -> dict:
    d = kb()
    a = d[d.alert_generated_flag]
    return {"transactions": int(len(d)), "alerts": int(len(a)), "alert_rate_pct": round(len(a) / len(d) * 100, 2),
            "severity": a.alert_severity.value_counts().to_dict(), "patterns": a.alert_primary_pattern.value_counts().to_dict(),
            "channels_alerts": a.channel.value_counts().to_dict(), "exposure_usd": round(float(a.potential_exposure_usd.sum()), 2)}


def answer(message: str, transaction_id: str | None, history: list[dict]) -> dict:
    ent = resolve(message)
    found = ent["found"]
    base = {"entities": ent, "sources": [], "provenance": [], "guards": []}

    # incorrect identifiers: say so, never guess
    if ent["unknown"]:
        return {**base, "intent": "lookup", "router": "none", "llm_used": False, "transaction_id": transaction_id,
                "answer": ("I could not find " + ", ".join(f"`{u}`" for u in ent["unknown"]) +
                           " in the dataset, so I cannot answer about it. Check the identifier (for example `TXN-SYN0002128`, `CUS-00039`, `DEV-00141`, `BEN-00007`)."),
                "not_found": ent["unknown"]}
    if ent["ambiguous"]:
        c = ent["ambiguous"][0]["candidates"]
        return {**base, "intent": "clarify", "router": "none", "llm_used": False, "transaction_id": transaction_id,
                "answer": "That name matches more than one record. Which did you mean?\n" + "\n".join(f"- `{x['id']}` {x['name']}" for x in c),
                "clarify": c}

    txn = (found.get("transaction") or [transaction_id] or [None])[0] if (found.get("transaction") or transaction_id) else None
    intent, router = llm.route_intent(message, bool(txn))
    dossier = build_dossier(txn) if txn else None

    summaries = []
    for kind in ("customer", "device", "beneficiary"):
        for eid in found.get(kind, [])[:2]:
            s = entity_summary(kind, eid)
            if s:
                summaries.append(s)
    if dossier and not summaries and intent in ("network", "device", "beneficiary"):
        f = dossier["observed_facts"]
        for kind, key in (("device", "device_id"), ("beneficiary", "beneficiary_id")):
            if (intent == "device" and kind == "device") or (intent in ("beneficiary", "network") and kind == "beneficiary") or intent == "network":
                v = f[kind].get(key)
                s = v and entity_summary(kind, v)
                if s:
                    summaries.append(s)

    if not dossier and not summaries:
        if intent == "stats" or "alert" in message.lower():
            pkg = {"overall_statistics": _overall_stats()}
            src = [{"type": "calculated", "ref": "overall alert statistics (Pandas)"}]
        else:
            return {**base, "intent": intent, "router": router, "llm_used": False, "transaction_id": None,
                    "answer": "Select a transaction (or mention a transaction, customer, device or beneficiary ID) so I can investigate from the data.",
                    "needs_context": True}
    else:
        pkg, src = {}, []

    sim = None
    if intent == "similar" or intent == "case_summary":
        sim = retrieval.similar(query_txn_id=txn, text=None if txn else message, k=5)
        if sim is None:
            base["guards"].append("Semantic index is not ready/unavailable; similar-activity retrieval skipped")
        elif sim:
            pkg["retrieved_similar_activity"] = sim
            src += [{"type": "retrieved", "ref": x["transaction_id"], "score": x["distance"]} for x in sim]

    if dossier:
        keys = SECTIONS.get(intent, SECTIONS["explain_flag"])
        pkg["transaction_id"] = txn
        pkg["hypothesis"] = dossier["hypothesis"]
        pkg["alert_summary"] = dossier["observed_facts"]["alert"]
        for k in keys:
            pkg[k] = dossier[k]
        for f in FACTS.get(intent, []):
            pkg.setdefault("observed_facts", {})[f] = dossier["observed_facts"][f]
        src.append({"type": "exact", "ref": txn})
        src.append({"type": "calculated", "ref": f"dossier for {txn}"})
    for s in summaries:
        pkg.setdefault("entity_summaries", []).append(s)
        src.append({"type": "calculated", "ref": f"{s['kind']} {s['id']} aggregates"})

    text = llm.synthesize(message, intent, pkg, history)
    llm_used = text is not None
    if llm_used:
        text, applied = llm.guard(text)
        base["guards"] += applied
        known = set(kb()[["transaction_id", "customer_id", "device_id", "beneficiary_id", "case_id"]].astype(str).values.ravel())
        bad = sorted({i for i in ID_RE.findall(text) if i not in known})
        if bad:
            base["guards"].append("Identifiers in the AI text not found in the data: " + ", ".join(bad))
        base["unverified_ids"] = bad
    else:
        text = _compose(dossier, intent, summaries, sim) if dossier else _compose_entities(summaries, pkg)

    prov = ["EXACT", "CALCULATED"] + (["RETRIEVED"] if sim else []) + (["AI_REASONING"] if llm_used else [])
    return {**base, "intent": intent, "router": router, "llm_used": llm_used, "model": llm.MODEL if llm_used else None,
            "transaction_id": txn, "answer": text, "sources": src, "provenance": prov,
            "llm_error": None if llm_used else llm.llm_state()["last_error"]}


def _compose_entities(summaries, pkg) -> str:
    if not summaries:
        return "```\n" + str(pkg.get("overall_statistics")) + "\n```\n_Deterministic answer._"
    L = []
    for s in summaries:
        L.append(f"### {s['kind'].title()} {s['id']}")
        for k, v in s.items():
            if k not in ("kind", "id"):
                L.append(f"- {k.replace('_', ' ')}: {v}")
        if s.get("institutional_terminal") or s.get("is_merchant"):
            L.append("- **Counter-evidence:** this is institutional infrastructure/a merchant, so many accounts/senders is expected.")
    L.append("\n_Deterministic answer: Groq reasoning layer was not used for this response._")
    return "\n".join(L)

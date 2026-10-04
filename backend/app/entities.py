"""Entity resolution: exact ID patterns first, RapidFuzz for names. Ambiguity is reported, never guessed."""
import re
from functools import lru_cache

from rapidfuzz import fuzz, process

from .store import kb

PATTERNS = {
    "transaction": re.compile(r"\bTXN-[A-Z]*\d+\b", re.I),
    "customer": re.compile(r"\bCUS-?\d+\b", re.I),
    "device": re.compile(r"\bDEV-?\d+\b", re.I),
    "beneficiary": re.compile(r"\bBEN-?\d+\b", re.I),
    "case": re.compile(r"\bCASE-?\d+\b", re.I),
}


def _norm(kind: str, v: str) -> str:
    v = v.upper()
    if kind == "customer" and "-" not in v:
        v = "CUS-" + v[3:]
    if kind == "device" and "-" not in v:
        v = "DEV-" + v[3:]
    if kind == "beneficiary" and "-" not in v:
        v = "BEN-" + v[3:]
    return v


@lru_cache(maxsize=1)
def _names():
    d = kb()
    c = d[["customer_id", "customer_name"]].drop_duplicates()
    b = d[d.beneficiary_id != ""][["beneficiary_id", "beneficiary_name"]].drop_duplicates()
    return (
        {r.customer_name: r.customer_id for r in c.itertuples()},
        {r.beneficiary_name: r.beneficiary_id for r in b.itertuples()},
    )


def resolve(text: str) -> dict:
    """Returns {found: {kind: [ids]}, unknown: [ids not in data], ambiguous: [{query, candidates}]}"""
    d = kb()
    found, unknown, ambiguous = {}, [], []
    for kind, pat in PATTERNS.items():
        for m in pat.findall(text or ""):
            v = _norm(kind, m)
            col = {"transaction": "transaction_id", "customer": "customer_id", "device": "device_id",
                   "beneficiary": "beneficiary_id", "case": "case_id"}[kind]
            if (d[col] == v).any():
                found.setdefault(kind, [])
                if v not in found[kind]:
                    found[kind].append(v)
            else:
                unknown.append(v)
    if not found.get("customer") and not found.get("beneficiary"):
        cust, ben = _names()
        # fuzzy name matching only when the user typed something name-like
        frag = re.search(r"SYN\s[\w+ '&-]*\w", text or "", re.I)
        if frag:  # name fragment typed: substring match first; ambiguity is reported, never guessed
            f = frag.group(0).lower()
            for pool, kind in ((cust, "customer"), (ben, "beneficiary")):
                cands = [n for n in pool if f in n.lower()]
                if len(cands) == 1:
                    found.setdefault(kind, []).append(pool[cands[0]])
                elif len(cands) > 1:
                    ambiguous.append({"query": text, "kind": kind, "total_matches": len(cands),
                                      "candidates": [{"id": pool[n], "name": n} for n in sorted(cands)[:5]]})
            if found or ambiguous:
                return {"found": found, "unknown": unknown, "ambiguous": ambiguous[:1]}
        for label, pool, kind in (("customer", cust, "customer"), ("beneficiary", ben, "beneficiary")):
            hits = process.extract(text, list(pool), scorer=fuzz.partial_ratio, limit=6, score_cutoff=88)
            hits = [h for h in hits if len(h[0]) > 6]
            if not hits:
                continue
            top = hits[0][1]
            tied = [h for h in hits if h[1] >= top - 1]
            if len(tied) == 1:  # one clear best match (e.g. the full name was typed)
                found.setdefault(kind, []).append(pool[tied[0][0]])
            elif not re.search(r"\d{3,}", text or "") or top < 100:
                ambiguous.append({"query": text, "kind": kind,
                                  "candidates": [{"id": pool[h[0]], "name": h[0]} for h in tied[:5]]})
    return {"found": found, "unknown": unknown, "ambiguous": ambiguous}

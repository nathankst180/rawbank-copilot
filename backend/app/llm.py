"""Groq reasoning layer (openai/gpt-oss-20b). The LLM is NOT the database: it only phrases and reasons over
the evidence package it is handed, and its output is post-checked."""
import json
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("copilot.llm")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
INTENTS = ["explain_flag", "behaviour_compare", "timeline", "beneficiary", "network", "device", "authentication",
           "velocity", "geography", "rules", "support", "counter", "false_positive", "next_action", "case_summary",
           "similar", "stats"]

KEYWORDS = [
    ("case_summary", ["summary", "summarise", "summarize", "case note", "write up"]),
    ("false_positive", ["false positive", "legitimate", "benign", "innocent"]),
    ("counter", ["counter", "weaken", "contradict", "against the", "evidence against"]),
    ("support", ["supports", "support the", "fraud hypothesis", "evidence for"]),
    ("next_action", ["next", "verify", "recommend", "what should", "escalate"]),
    ("similar", ["similar", "resemble", "like this", "comparable"]),
    ("timeline", ["24 hours", "timeline", "previous", "history", "what happened", "before this"]),
    ("behaviour_compare", ["normal behaviour", "normal behavior", "baseline", "median", "typical", "compare"]),
    ("authentication", ["login", "password", "credential", "sim ", "sim-", "authentication", "auth"]),
    ("velocity", ["velocity", "burst", "minutes", "rapid"]),
    ("geography", ["travel", "location", "geograph", "cross-border", "cross border", "country"]),
    ("network", ["other customers", "network", "senders", "mule", "receive"]),
    ("beneficiary", ["beneficiary", "payee", "newly added"]),
    ("device", ["device", "accounts"]),
    ("rules", ["rule", "triggered", "fr-"]),
    ("stats", ["how many", "count", "total", "average", "statistic", "how much"]),
    ("explain_flag", ["why", "flag", "suspicious"]),
]


_bad_key = {"v": None}


def _client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key or "your_groq" in key.lower() or _bad_key["v"] == key:
        return None  # not configured, or this exact key was already rejected (restart after fixing .env)
    from groq import Groq
    return Groq(api_key=key, timeout=30)


def keyword_intent(msg: str) -> str:
    m = f" {msg.lower()} "
    for intent, kws in KEYWORDS:
        if any(k in m for k in kws):
            return intent
    return "explain_flag"


def llm_state() -> dict:
    return {"configured": bool(os.getenv("GROQ_API_KEY", "").strip()) and "your_groq" not in os.getenv("GROQ_API_KEY", ""), "key_rejected": _bad_key["v"] is not None, "model": MODEL, "last_error": _last_error["msg"]}


_last_error = {"msg": None}


def _chat(messages, max_tokens=1400, json_mode=False):
    c = _client()
    if c is None:
        return None
    try:
        kw = {"model": MODEL, "messages": messages, "temperature": 0.2, "max_completion_tokens": max_tokens,
              "reasoning_effort": "low"}
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        r = c.chat.completions.create(**kw)
        _last_error["msg"] = None
        return (r.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        _last_error["msg"] = f"{type(e).__name__}: {str(e)[:160]}"
        if type(e).__name__ == "AuthenticationError":
            _bad_key["v"] = os.getenv("GROQ_API_KEY", "").strip()
        log.warning("groq call failed: %s", _last_error["msg"])
        return None


def route_intent(message: str, has_txn: bool) -> tuple[str, str]:
    """Returns (intent, router) where router is 'groq' or 'keywords'."""
    out = _chat([
        {"role": "system", "content": "You route questions from a fraud analyst to one intent. Reply with JSON "
         '{"intent": "<one of: ' + ", ".join(INTENTS) + '>"} and nothing else.'},
        {"role": "user", "content": f"Transaction in focus: {has_txn}. Question: {message}"},
    ], max_tokens=200, json_mode=True)
    if out:
        try:
            i = json.loads(out).get("intent")
            if i in INTENTS:
                return i, "groq"
        except Exception:  # noqa: BLE001
            pass
    return keyword_intent(message), "keywords"


SYSTEM = """You are the Sentient Fraud Investigation Copilot for a SYNTHETIC banking environment (academic exercise).
You assist a fraud analyst. You are given an EVIDENCE PACKAGE as JSON. It is your ONLY source of facts.

Rules:
- Use only facts present in the package. Never invent transactions, IDs, amounts, dates, customers or rules.
- If something needed is missing, say "insufficient evidence" and name what is missing.
- Keep these apart and label them: Observed facts (exact), Derived metrics (calculated), Triggered rules,
  Supporting evidence, Counter-evidence, Evidence gaps, Recommended analyst action. Include only the parts relevant to the question.
- Always weigh counter-evidence and say when the activity may be a false positive. High value alone is not fraud evidence.
- Use hedged wording: "The available evidence is consistent with possible ...". Never say a person committed fraud.
- Never assign or imply the disposition CONFIRMED_FRAUD; dispositions are human decisions.
- ATM/POS terminals and merchants legitimately touch many accounts/senders.
- Rules FR-01..FR-20 are synthetic workshop rules, not the bank's real policies.
- Cite transaction/customer/device/beneficiary IDs exactly as given. Be concise (under 300 words), use markdown headings and bullets."""


def synthesize(question: str, intent: str, package: dict, history: list[dict]) -> str | None:
    msgs = [{"role": "system", "content": SYSTEM}]
    for h in history[-4:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
    msgs.append({"role": "user", "content": f"Question: {question}\nIntent: {intent}\n\nEVIDENCE PACKAGE:\n"
                 + json.dumps(package, default=str)[:24000]})
    return _chat(msgs)


_BAD = [(re.compile(r"\b(has|have) committed fraud\b", re.I), "shows indicators consistent with possible fraud"),
        (re.compile(r"\bis (definitely|certainly|clearly) (fraud|fraudulent)\b", re.I), "is consistent with possible fraud indicators"),
        (re.compile(r"\bconfirmed fraud\b", re.I), "possible fraud (unconfirmed)")]


def guard(text: str) -> tuple[str, list[str]]:
    """Post-check LLM output against the data policy. Returns (clean_text, applied_guards)."""
    applied = []
    for pat, rep in _BAD:
        if pat.search(text):
            text = pat.sub(rep, text)
            applied.append(f"rewrote definitive fraud wording ({pat.pattern[:30]}...)")
    return text, applied

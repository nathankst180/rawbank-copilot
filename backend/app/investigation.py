"""Deterministic investigation engine. Everything here is EXACT data or CALCULATED from the CSV.
No LLM involvement: this is the evidence the LLM is later allowed to reason over.

Synthetic workshop rules only - not Rawbank's internal policies."""
import math

import pandas as pd

from .store import kb, row

RULES = {
    "FR-01": ("Amount >= 5x customer median", 12), "FR-02": ("Amount >= 10x customer median", 20),
    "FR-03": ("New beneficiary", 12), "FR-04": ("New / untrusted device", 12),
    "FR-05": ("3+ failed logins in 30 min", 14), "FR-06": ("Password reset within 24h", 10),
    "FR-07": ("Recent SIM change", 8), "FR-08": ("4+ transactions in 10 min", 14),
    "FR-09": ("Abnormal 1-hour outbound value", 12), "FR-10": ("Impossible travel (hard trigger)", 20),
    "FR-11": ("Unusual country/location", 7), "FR-12": ("VPN / proxy signal", 5),
    "FR-13": ("Device used across 3+ accounts", 13), "FR-14": ("Beneficiary receives from 5+ customers", 15),
    "FR-15": ("Card-not-present + unusual behaviour", 12), "FR-16": ("Unusual transaction time", 4),
    "FR-17": ("New device + new beneficiary", 12), "FR-18": ("Failed logins + reset + new device (hard trigger)", 18),
    "FR-19": ("New cross-border beneficiary + abnormal value", 14),
    "FR-20": ("Incomplete corporate approval (hard trigger)", 25),
}
TERMINALS = {"ATM_TERMINAL", "POS_TERMINAL"}
PATTERN_WORDING = {
    "ACCOUNT_TAKEOVER": "possible account takeover",
    "NEW_BENEFICIARY_HIGH_VALUE": "a possible high-value payment to a newly added beneficiary",
    "VELOCITY_BURST": "a possible velocity burst", "IMPOSSIBLE_TRAVEL": "possible impossible-travel activity",
    "SHARED_DEVICE": "possible shared-device activity", "MULE_BENEFICIARY": "a possible mule-like beneficiary",
    "CARD_NOT_PRESENT": "a possible card-not-present anomaly",
    "CREDENTIAL_RESET_ABUSE": "possible credential-reset abuse",
    "CORPORATE_APPROVAL_ANOMALY": "a corporate approval workflow anomaly",
    "CROSS_BORDER_ANOMALY": "a possible cross-border anomaly", "OTHER": "an anomaly that does not match a named pattern",
}
PATTERN_ACTIONS = {
    "ACCOUNT_TAKEOVER": ["Contact the customer through a verified channel to confirm the transaction",
                         "Review recent credential, device and SIM-change events",
                         "Consider a temporary hold pending verification"],
    "NEW_BENEFICIARY_HIGH_VALUE": ["Verify the beneficiary with the customer via a known channel",
                                   "Check how the beneficiary was added (device, session, timing)"],
    "VELOCITY_BURST": ["Review the burst as a sequence (timeline) and check whether amounts were split",
                       "Confirm whether a scheduled/batch process explains the pattern"],
    "IMPOSSIBLE_TRAVEL": ["Compare device/IP geography with the customer's last known location"],
    "SHARED_DEVICE": ["Review other accounts using the device and whether the device is institutional (ATM/POS)"],
    "MULE_BENEFICIARY": ["Review all senders to this beneficiary and onward movement of funds",
                         "Consider Tier-2 network review"],
    "CARD_NOT_PRESENT": ["Check merchant, entry mode and prior merchant history; consider cardholder contact"],
    "CREDENTIAL_RESET_ABUSE": ["Review reset origin (device/IP) and activity after reset"],
    "CORPORATE_APPROVAL_ANOMALY": ["Obtain the approval record from the corporate workflow; hold until complete"],
    "CROSS_BORDER_ANOMALY": ["Check the customer's cross-border history and expected corridors"],
}


def _v(x):
    """JSON-safe scalar."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(x, "item"):
        x = x.item()
    return x


def _pick(r, cols):
    return {c: _v(r[c]) for c in cols if c in r.index}


def _usd(x):
    return None if x is None or pd.isna(x) else f"${x:,.2f}"


def _fmt(cond, text):
    return text if cond else ""


def build_dossier(txn_id: str):
    r = row(txn_id)
    if r is None:
        return None
    d = kb()
    codes = [c for c in str(r.alert_reason_codes).split("|") if c in RULES]
    cust = d[d.customer_id == r.customer_id]
    before = cust[cust.ts < r.ts]
    day = cust[(cust.ts >= r.ts - pd.Timedelta(hours=24)) & (cust.ts <= r.ts)]
    dev = d[d.device_id == r.device_id] if r.device_id else d.iloc[0:0]
    ben = d[d.beneficiary_id == r.beneficiary_id] if r.beneficiary_id else d.iloc[0:0]

    # ---- 1. observed facts (exact) ----
    facts = {
        "transaction": _pick(r, ["transaction_id", "event_timestamp_local", "transaction_type", "direction", "amount",
                                 "currency", "amount_usd_equiv", "channel", "channel_action", "payment_rail",
                                 "transaction_status", "narration", "is_cross_border", "origin_country",
                                 "destination_country"]),
        "customer": _pick(r, ["customer_id", "customer_name", "customer_type", "customer_segment", "resident_status",
                              "home_city", "relationship_tenure_days", "kyc_risk_band", "pep_flag",
                              "monthly_inflow_usd_equiv"]),
        "device": _pick(r, ["device_id", "device_type", "device_os", "device_trusted_flag", "device_first_seen_days",
                            "device_accounts_seen_30d", "ip_country", "ip_city", "ip_risk_score", "vpn_proxy_flag"]),
        "beneficiary": _pick(r, ["beneficiary_id", "beneficiary_name", "beneficiary_type", "beneficiary_relationship",
                                 "beneficiary_age_days", "beneficiary_prior_txn_count",
                                 "beneficiary_distinct_sender_count_30d", "merchant_name"]),
        "authentication": _pick(r, ["auth_method", "auth_success_flag", "login_failures_30m", "password_reset_hours_ago",
                                    "sim_swap_days_ago", "approvals_required", "approvals_completed"]),
        "geography": _pick(r, ["txn_city", "txn_province", "previous_txn_city", "geo_distance_from_home_km",
                               "impossible_travel_flag"]),
        "alert": _pick(r, ["alert_generated_flag", "alert_id", "alert_score", "alert_severity", "alert_primary_pattern",
                           "alert_reason_codes", "potential_exposure_usd", "case_id", "case_status", "analyst_queue",
                           "human_disposition", "escalation_required_flag", "escalation_tier"]),
    }

    # ---- 2. derived metrics (calculated from the CSV, cross-checked against stored fields) ----
    prior_to_ben = int(((before.beneficiary_id == r.beneficiary_id) & (r.beneficiary_id != "")).sum())
    recomputed_median = float(before.amount_usd_equiv.median()) if len(before) else None
    metrics = {
        "amount_to_median_ratio": _v(r.amount_to_median_ratio),
        "customer_median_txn_usd_90d": _v(r.customer_median_txn_usd_90d),
        "customer_avg_txn_usd_30d": _v(r.customer_avg_txn_usd_30d),
        "txn_count_10m": _v(r.txn_count_10m), "txn_count_1h": _v(r.txn_count_1h),
        "outbound_amount_1h_usd": _v(r.outbound_amount_1h_usd), "minutes_since_prev_txn": _v(r.minutes_since_prev_txn),
        "behavioral_deviation_score": _v(r.behavioral_deviation_score),
        "customer_total_txns_in_dataset": int(len(cust)),
        "customer_txns_before_this_one": int(len(before)),
        "customer_txns_prior_24h": int(len(day) - 1),
        "customer_alerts_in_dataset": int(cust.alert_generated_flag.sum()),
        "recomputed_prior_median_usd": None if recomputed_median is None else round(recomputed_median, 2),
        "prior_txns_by_this_customer_to_beneficiary": prior_to_ben,
        "device_distinct_customers_in_dataset": int(dev.customer_id.nunique()) if len(dev) else None,
        "device_total_txns_in_dataset": int(len(dev)),
        "beneficiary_distinct_senders_in_dataset": int(ben.customer_id.nunique()) if len(ben) else None,
        "beneficiary_total_txns_in_dataset": int(len(ben)),
    }

    # ---- 3. triggered rules ----
    rules = [{"code": c, "description": RULES[c][0], "weight": RULES[c][1]} for c in codes]

    # ---- 4. supporting evidence (from fired rules, with values) ----
    ratio, nn = r.amount_to_median_ratio, pd.notna
    val = {
        "FR-01": _fmt(nn(ratio), f"amount is {ratio:.1f}x the customer's 90-day median"),
        "FR-02": _fmt(nn(ratio), f"amount is {ratio:.1f}x the customer's 90-day median"),
        "FR-03": "first-time beneficiary for this customer", "FR-04": "new or untrusted device",
        "FR-05": _fmt(nn(r.login_failures_30m), f"{r.login_failures_30m:.0f} failed logins in 30 minutes"),
        "FR-06": _fmt(nn(r.password_reset_hours_ago), f"password reset {r.password_reset_hours_ago:.1f}h before the transaction"),
        "FR-07": _fmt(nn(r.sim_swap_days_ago), f"SIM change {r.sim_swap_days_ago:.0f} day(s) before"),
        "FR-08": _fmt(nn(r.txn_count_10m), f"{r.txn_count_10m:.0f} transactions within 10 minutes"),
        "FR-09": _fmt(nn(r.outbound_amount_1h_usd), f"outbound value in the last hour is {_usd(r.outbound_amount_1h_usd)}"),
        "FR-10": _fmt(nn(r.geo_distance_from_home_km), f"impossible travel ({r.geo_distance_from_home_km:,.0f} km from home)"),
        "FR-11": "unusual country/location for this customer", "FR-12": "VPN / proxy signal",
        "FR-13": _fmt(nn(r.device_accounts_seen_30d), f"device seen across {r.device_accounts_seen_30d:.0f} accounts (30d)"),
        "FR-14": _fmt(nn(r.beneficiary_distinct_sender_count_30d), f"beneficiary received from {r.beneficiary_distinct_sender_count_30d:.0f} distinct senders (30d)"),
        "FR-15": "card-not-present with unusual behaviour", "FR-16": "unusual transaction time",
        "FR-17": "new device combined with a new beneficiary", "FR-18": "failed logins + password reset + new device",
        "FR-19": "new cross-border beneficiary with abnormal value",
        "FR-20": _fmt(nn(r.approvals_required), f"corporate approvals incomplete ({r.approvals_completed:.0f}/{r.approvals_required:.0f})"),
    }
    sup = [f"{c}: {val.get(c) or RULES[c][0]}" for c in codes]

    # ---- 5. counter-evidence (ruleset section 6 + institutional context) ----
    ctr = []
    if r.device_trusted_flag and (r.beneficiary_prior_txn_count or 0) > 0:
        ctr.append("Trusted device with an established beneficiary (-12 in the workshop scoring)")
    if r.recurring_or_scheduled_flag:
        ctr.append("Recurring / scheduled known payment (-10)")
    if r.resident_status == "DIASPORA" and r.is_cross_border:
        ctr.append("Diaspora customer: cross-border activity can be expected (-10)")
    if r.corporate_payment_flag and nn(r.approvals_required) and r.approvals_completed >= r.approvals_required:
        ctr.append("Corporate payment with a complete approval chain (-15)")
    if nn(ratio) and ratio <= 2 and r.customer_segment in {"PREMIUM", "PRESTIGE", "INFINITE", "CORPORATE", "SME"}:
        ctr.append("High-value segment behaving within its normal baseline (-8)")
    if r.device_type in TERMINALS and "FR-13" in codes:
        ctr.append(f"{r.device_type} is shared institutional infrastructure; many accounts per device is expected")
    if r.beneficiary_type == "MERCHANT" and "FR-14" in codes:
        ctr.append("Beneficiary is a merchant; many distinct senders is expected")
    if not codes:
        ctr.append("No synthetic fraud rule fired for this transaction")

    # ---- control exceptions are NOT fraud evidence ----
    controls = []
    if r.channel == "VISA_DIRECT" and nn(r.amount_usd_equiv) and r.amount_usd_equiv > 1000:
        controls.append("Visa Direct per-transaction limit (USD 1,000) exceeded: a control exception, not fraud proof")
    if r.channel == "ATM" and "DEPOSIT" in str(r.transaction_type).upper() and r.amount_usd_equiv > 4000:
        controls.append("ATM deposit above the modelled USD 4,000 limit: a product/control exception")

    # ---- 6. evidence gaps ----
    gaps = []
    if r.human_disposition == "UNREVIEWED":
        gaps.append("No human disposition recorded yet (UNREVIEWED)")
    if not r.beneficiary_id:
        gaps.append("No beneficiary on this transaction, so network analysis is not applicable")
    if r.auth_success_flag is False:
        gaps.append("Authentication failed; the actor behind the attempt is unknown")
    if pd.isna(r.password_reset_hours_ago) and pd.isna(r.sim_swap_days_ago):
        gaps.append("No credential-reset or SIM-change event recorded for this customer window")
    if len(before) < 5:
        gaps.append(f"Only {len(before)} earlier transactions for this customer: baseline statistics are weak")
    gaps += ["The dataset has no customer confirmation, so intent cannot be established from data alone",
             "All data is synthetic; no external intelligence or real device fingerprint is available"]

    # ---- hypothesis + false-positive view (heuristic, clearly labelled) ----
    pattern = r.alert_primary_pattern or ""
    s_pts = sum(RULES[c][1] for c in codes)
    if not r.alert_generated_flag:
        hypothesis = "No alert was generated; the available evidence does not indicate suspicious activity."
        fp = "NOT_APPLICABLE"
    else:
        hypothesis = (f"The available evidence is consistent with {PATTERN_WORDING.get(pattern, 'an anomaly')}. "
                      "This is a hypothesis for analyst review, not a finding of fraud.")
        n_ctr = len([c for c in ctr if not c.startswith("No synthetic")])
        fp = "HIGH" if (n_ctr >= 2 and s_pts < 40) else "MODERATE" if n_ctr >= 1 else "LOW"

    actions = list(PATTERN_ACTIONS.get(pattern, ["Review the triggered rules and related activity"]))
    if fp in ("MODERATE", "HIGH"):
        actions.append("Weigh the counter-evidence: this may be a false positive; confirm before restricting the customer")
    if r.escalation_required_flag:
        actions.append(f"Escalation is flagged ({r.escalation_tier}); route to the {r.analyst_queue} queue")
    actions.append("Record the analyst disposition; this system never sets CONFIRMED_FRAUD")

    # ---- related activity ----
    def lite(df, n=8):
        t = df.sort_values("ts", ascending=False).head(n)
        return [{"transaction_id": x.transaction_id, "ts": _v(x.ts), "customer_id": x.customer_id,
                 "amount_usd": _v(x.amount_usd_equiv), "channel": x.channel, "alert": bool(x.alert_generated_flag),
                 "severity": x.alert_severity or None} for x in t.itertuples()]

    related = {
        "customer_last_24h": lite(day[day.transaction_id != r.transaction_id], 12),
        "same_device": lite(dev[dev.transaction_id != r.transaction_id]),
        "same_beneficiary": lite(ben[ben.transaction_id != r.transaction_id]),
        "device_other_customers": sorted(set(dev.customer_id) - {r.customer_id})[:15],
        "beneficiary_other_senders": sorted(set(ben.customer_id) - {r.customer_id})[:15],
    }

    return {
        "transaction_id": txn_id, "alerted": bool(r.alert_generated_flag),
        "observed_facts": facts, "derived_metrics": metrics, "triggered_rules": rules,
        "supporting_evidence": sup, "counter_evidence": ctr, "control_exceptions": controls,
        "evidence_gaps": gaps, "hypothesis": hypothesis, "false_positive_likelihood": fp,
        "false_positive_note": "Heuristic: counts workshop counter-evidence against rule weight; not a probability.",
        "recommended_actions": actions, "related_activity": related,
        "provenance": {"observed_facts": "EXACT", "derived_metrics": "CALCULATED", "triggered_rules": "EXACT",
                       "supporting_evidence": "CALCULATED", "counter_evidence": "CALCULATED",
                       "evidence_gaps": "CALCULATED", "recommended_actions": "CALCULATED"},
    }


def entity_summary(kind: str, eid: str):
    d = kb()
    col = {"customer": "customer_id", "device": "device_id", "beneficiary": "beneficiary_id"}[kind]
    x = d[d[col] == eid]
    if x.empty:
        return None
    a = x[x.alert_generated_flag]
    out = {"kind": kind, "id": eid, "transactions": int(len(x)), "alerts": int(len(a)),
           "alert_rate_pct": round(len(a) / len(x) * 100, 1), "total_usd": round(float(x.amount_usd_equiv.sum()), 2),
           "first_seen": _v(x.ts.min()), "last_seen": _v(x.ts.max()),
           "severity_counts": a.alert_severity.value_counts().to_dict(),
           "top_patterns": a.alert_primary_pattern.value_counts().head(3).to_dict(),
           "channels": x.channel.value_counts().to_dict(),
           "recent_alert_ids": list(a.sort_values("ts", ascending=False).transaction_id.head(8))}
    f = x.iloc[0]
    if kind == "customer":
        out.update(_pick(f, ["customer_name", "customer_type", "customer_segment", "resident_status", "kyc_risk_band"]))
        out["distinct_devices"] = int(x.device_id.nunique())
        out["distinct_beneficiaries"] = int(x[x.beneficiary_id != ""].beneficiary_id.nunique())
    if kind == "device":
        out.update(_pick(f, ["device_type", "device_os", "device_trusted_flag"]))
        out["distinct_customers"] = int(x.customer_id.nunique())
        out["institutional_terminal"] = f.device_type in TERMINALS
    if kind == "beneficiary":
        out.update(_pick(f, ["beneficiary_name", "beneficiary_type"]))
        out["distinct_senders"] = int(x.customer_id.nunique())
        out["is_merchant"] = f.beneficiary_type == "MERCHANT"
    return out

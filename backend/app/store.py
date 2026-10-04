"""Exact data layer (Pandas). Loads ONLY RAWBANK_SENTIENT_KB.csv - never the ground-truth file.
Synthetic academic data; not Rawbank's real data."""
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()
BOOL_COLS = ["alert_generated_flag", "escalation_required_flag", "device_trusted_flag", "new_device_flag",
             "new_beneficiary_flag", "is_cross_border", "vpn_proxy_flag", "impossible_travel_flag",
             "unusual_time_flag", "recurring_or_scheduled_flag", "corporate_payment_flag",
             "auth_success_flag", "pep_flag"]
NUM_COLS = ["amount", "amount_usd_equiv", "alert_score", "potential_exposure_usd", "customer_median_txn_usd_90d",
            "customer_avg_txn_usd_30d", "amount_to_median_ratio", "txn_count_10m", "txn_count_1h",
            "outbound_amount_1h_usd", "minutes_since_prev_txn", "geo_distance_from_home_km",
            "behavioral_deviation_score", "device_accounts_seen_30d", "device_first_seen_days",
            "beneficiary_distinct_sender_count_30d", "beneficiary_prior_txn_count", "beneficiary_age_days",
            "login_failures_30m", "password_reset_hours_ago", "sim_swap_days_ago", "approvals_required",
            "approvals_completed", "ip_risk_score", "relationship_tenure_days", "monthly_inflow_usd_equiv"]


def csv_path() -> Path:
    p = Path(__file__).resolve().parents[1] / os.getenv("DATA_PATH", "data/RAWBANK_SENTIENT_KB.csv")
    if "GROUND_TRUTH" in p.name.upper():
        raise RuntimeError("Ground-truth data must never be loaded by the application.")
    if not p.exists():
        raise FileNotFoundError(f"Canonical dataset not found: {p}")
    return p


@lru_cache(maxsize=1)
def kb() -> pd.DataFrame:
    df = pd.read_csv(csv_path(), keep_default_na=False, dtype=str)
    for c in BOOL_COLS:
        if c in df:
            df[c] = df[c].str.upper().isin(["TRUE", "1", "YES"])
    for c in NUM_COLS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_datetime(df["event_timestamp_local"], errors="coerce")
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].replace({"NONE": ""})
    return df.sort_values("ts").reset_index(drop=True)


def row(txn_id: str):
    d = kb()
    m = d[d.transaction_id == txn_id]
    return None if m.empty else m.iloc[0]

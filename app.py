"""
Fission Pulse
A public tracker for Fission (fission.xyz) liquidity for tokenized funds.

Reads the same public fund list the Fission redeem page loads, saves a snapshot
every hour, and serves a dashboard at http://127.0.0.1:5000

Run:
    pip install -r requirements.txt
    python app.py
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, send_from_directory

API_URL = "https://api.fission.xyz/graphql"
POLL_SECONDS = 60 * 60  # one snapshot per hour, keeps load on their API tiny
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
SNAPSHOTS = DATA_DIR / "snapshots.jsonl"

# Same public query the redeem page (redeem.fission.xyz) runs on load.
QUERY = """
query list_redeemables {
  redeemables {
    id name symbol paused published settlement_balance
    commission_fee_info {
      current_unliquidated_total days_until_next_redemption total_aum
      fee_schedule { boundaries entries { days_until fee_percentages } }
    }
    networks { network published deposit_token { address symbol } }
    price_feed_protocol
  }
}
"""

app = Flask(__name__, static_folder="static")
_lock = threading.Lock()


# ---------- collecting ----------

def current_fee(entries, days_left):
    """Fee for the smallest size tier at the fund's current point in its cycle."""
    if not entries:
        return None
    if days_left is None:
        return entries[-1]["fee_percentages"][0]
    for e in entries:
        if e["days_until"] >= days_left:
            return e["fee_percentages"][0]
    return entries[-1]["fee_percentages"][0]


def fetch_snapshot():
    r = requests.post(
        API_URL,
        json={"query": QUERY},
        headers={"User-Agent": "FissionPulse/1.0 (public tracker)"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()["data"]["redeemables"]

    funds = []
    for f in rows:
        if not f.get("published"):  # only funds Fission shows publicly
            continue
        c = f.get("commission_fee_info") or {}
        sched = (c.get("fee_schedule") or {}).get("entries") or []
        fees = [e["fee_percentages"][0] for e in sched]
        funds.append({
            "id": f["id"],
            "name": f["name"],
            "paused": f["paused"],
            "liquidity": f.get("settlement_balance") or 0,
            "inventory": c.get("current_unliquidated_total") or 0,
            "days_to_window": c.get("days_until_next_redemption"),
            "fund_aum": c.get("total_aum"),
            "fee_now": current_fee(sched, c.get("days_until_next_redemption")),
            "fee_min": min(fees) if fees else None,
            "fee_max": max(fees) if fees else None,
            "chains": [n["network"] for n in f["networks"] if n.get("published")],
            "oracle": f.get("price_feed_protocol"),
        })

    return {"ts": datetime.now(timezone.utc).isoformat(), "funds": funds}


def save_snapshot(snap):
    DATA_DIR.mkdir(exist_ok=True)
    with _lock, open(SNAPSHOTS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap) + "\n")


def load_snapshots():
    if not SNAPSHOTS.exists():
        return []
    with _lock, open(SNAPSHOTS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def collector_loop():
    while True:
        try:
            snap = fetch_snapshot()
            save_snapshot(snap)
            print(f"[{snap['ts']}] saved snapshot of {len(snap['funds'])} funds")
        except Exception as e:  # keep running if the API hiccups
            print("snapshot failed:", e)
        time.sleep(POLL_SECONDS)


# ---------- analysis ----------

def pools(funds, key):
    """Fission shares liquidity and inventory across groups of funds.
    Funds reporting the exact same number sit in the same pool, so we count each pool once."""
    groups = {}
    for f in funds:
        k = round(f[key], 2)
        groups.setdefault(k, []).append(f["id"])
    return [{"value": k, "funds": v} for k, v in sorted(groups.items(), reverse=True)]


def summarize(snap):
    funds = snap["funds"]
    liq_pools = pools(funds, "liquidity")
    inv_pools = [p for p in pools(funds, "inventory") if p["value"] >= 1]
    return {
        "ts": snap["ts"],
        "total_liquidity": sum(p["value"] for p in liq_pools),
        "total_inventory": sum(p["value"] for p in inv_pools),
        "fund_count": len(funds),
        "chains": sorted({c for f in funds for c in f["chains"]}),
        "liquidity_pools": liq_pools,
        "inventory_pools": inv_pools,
        "funds": funds,
    }


def activity(snaps, min_change=1000):
    """Infer activity from inventory moves between snapshots.
    Inventory up   -> Fission bought fund tokens from holders (exits)
    Inventory down -> Fission redeemed tokens back to the fund"""
    events = []
    prev = None
    for s in snaps:
        cur = {tuple(p["funds"]): p["value"] for p in pools(s["funds"], "inventory")}
        if prev is not None:
            for funds, val in cur.items():
                before = prev.get(funds)
                if before is None:
                    continue
                diff = val - before
                if abs(diff) >= min_change:
                    events.append({
                        "ts": s["ts"],
                        "funds": list(funds),
                        "type": "exit" if diff > 0 else "redeemed_to_fund",
                        "amount": abs(diff),
                    })
        prev = cur
    return events[::-1]


# ---------- web ----------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/latest")
def api_latest():
    snaps = load_snapshots()
    if not snaps:
        return jsonify({"error": "no data yet"}), 503
    return jsonify(summarize(snaps[-1]))


@app.route("/api/history")
def api_history():
    snaps = load_snapshots()
    series = []
    for s in snaps:
        sm = summarize(s)
        series.append({"ts": s["ts"], "liquidity": sm["total_liquidity"],
                       "inventory": sm["total_inventory"]})
    return jsonify({"series": series, "events": activity(snaps)})


if __name__ == "__main__":
    threading.Thread(target=collector_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)

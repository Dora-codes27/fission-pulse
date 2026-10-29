# Fission Pulse

An independent tracker for [Fission](https://fission.xyz), the liquidity layer for tokenized funds.

It shows:

* How much USDC exit liquidity Fission has ready, pool by pool
* How much in fund positions Fission is holding while it waits to redeem them
* What an early exit costs today for each fund, next to how long the fund makes holders wait
* A history chart and an activity log that fill in over time

## Run it (Windows)

Double click `run.bat`, or in a terminal:

```
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

Leave it running. It saves one snapshot every hour into `data/snapshots.jsonl`. The chart and activity log need at least two snapshots, so check back after a few hours.

## Where the data comes from

The same public fund list that redeem.fission.xyz loads in your browser (`api.fission.xyz/graphql`, the `redeemables` query). Only funds Fission lists publicly are shown. One request per hour, so the load on their API is tiny.

## How activity is worked out

Fission buys fund tokens from holders and holds them until the fund's own redemption window.

* Holdings go up between snapshots: holders exited through Fission
* Holdings go down: Fission redeemed those tokens back to the fund

Changes under $1,000 are ignored. Some funds share one pool, so their numbers are counted once.

Not affiliated with Fission Labs. Not investment advice.

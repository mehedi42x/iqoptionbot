#!/usr/bin/env python3
"""
Loser forensics for emacombo v1.

Replays the strategy EXACTLY (verifies trade-for-trade match with
backtest_trades_60s.csv), then computes rich price-action features for every
signal candle so we can find WHY losers lost -- and fix them by changing
DIRECTION (flip), not by filtering (trade count must not decrease).

Split: TRAIN = 2026-07-12..2026-08-31, HOLDOUT = 2026-09-01..2026-09-10.
Tuning decisions must be made on TRAIN only.
"""
import csv
from collections import defaultdict
from datetime import datetime, timezone

from strategies.emacombo import Strategy

CSV_FILE = "candles_asset_1861_60s_365d.csv"
HOLDOUT_START = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()

# ---- strategy constants (mirror of emacombo v1) ----
EMA_FAST, EMA_SLOW, ATR_P = 9, 12, 14
MAXC = 300


def ema(values, period):
    e = sum(values[:period]) / period
    a = 2.0 / (period + 1.0)
    for v in values[period:]:
        e = v * a + e * (1.0 - a)
    return e


def atr(candles, period):
    trs = []
    for i in range(len(candles) - period, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        trs.append(max(cur["high"] - cur["low"],
                       abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
    return sum(trs) / period


def load():
    rows = []
    with open(CSV_FILE, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"ts": float(r["timestamp"]),
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    rows.sort(key=lambda c: c["ts"])
    return rows


def replay(rows):
    """Replay with own indicator copy + Strategy for signal verification."""
    strat = Strategy()
    win = []          # rolling window (mirror)
    feats = []        # per entry-candle-i feature dict (i>=1)
    for i, c in enumerate(rows):
        sig = strat.update_candle(60, {"timestamp": c["ts"], "open": c["open"],
                                       "high": c["high"], "low": c["low"],
                                       "close": c["close"]})
        st = strat.get_status()
        win.append(c)
        if len(win) > MAXC:
            win.pop(0)
        if i == 0:
            continue
        k = rows[i - 1]                       # just-closed signal candle
        completed = win[:-1]
        f = {"i": i, "entry_ts": c["ts"], "entry_price": c["open"],
             "v1_signal": sig, "v1_module": st.get("last_module"),
             "v1_reason": st.get("no_trade_reason"),
             "split": "HOLDOUT" if c["ts"] >= HOLDOUT_START else "TRAIN"}
        # outcome with v1 direction (also usable for hypothetical flips)
        exp_price = rows[i + 1]["open"] if i + 1 < len(rows) else None
        f["expiry_price"] = exp_price
        if sig and exp_price is not None:
            f["v1_result"] = ("WIN" if (exp_price > c["open"] if sig == "CALL"
                                        else exp_price < c["open"])
                              else ("DRAW" if exp_price == c["open"] else "LOSS"))
        else:
            f["v1_result"] = None
        # --- indicators as v1 sees them ---
        if len(completed) >= max(EMA_SLOW, ATR_P + 1):
            closes = [x["close"] for x in completed]
            e9, e12, a = ema(closes, EMA_FAST), ema(closes, EMA_SLOW), atr(completed, ATR_P)
            o, h, l, cc = k["open"], k["high"], k["low"], k["close"]
            rng = h - l
            body = abs(cc - o)
            bullish = cc > o
            f.update({
                "ema9": e9, "ema12": e12, "atr": a,
                "dir": "BULLISH" if e9 > e12 else ("BEARISH" if e9 < e12 else "NEUTRAL"),
                "bullish": bullish,
                "range": rng, "body": body,
                "body_ratio": (body / rng) if rng > 0 else 0,
                "range_atr": (rng / a) if a > 0 else 0,
                "pos_high": ((cc - l) / rng) if rng > 0 else 0.5,   # closeness to high
                "pos_low": ((h - cc) / rng) if rng > 0 else 0.5,    # closeness to low
                "pos": (((cc - l) / rng) if bullish else ((h - cc) / rng)) if rng > 0 else 0.5,
                "up_wick": ((h - max(o, cc)) / rng) if rng > 0 else 0,
                "lo_wick": ((min(o, cc) - l) / rng) if rng > 0 else 0,
                "ema_gap_atr": ((e9 - e12) / a) if a > 0 else 0,
                "overext_atr": ((cc - e9) / a) if a > 0 else 0,      # close vs fast EMA
                "overext12_atr": ((cc - e12) / a) if a > 0 else 0,
                "mom2_atr": ((cc - rows[i - 2]["close"]) / a) if (a > 0 and i >= 2) else 0,
                "prev_bull": (rows[i - 2]["close"] > rows[i - 2]["open"]) if i >= 2 else None,
                "prev_body_atr": (abs(rows[i - 2]["close"] - rows[i - 2]["open"]) / a) if (a > 0 and i >= 2) else 0,
                "hour": datetime.fromtimestamp(k["ts"], tz=timezone.utc).hour,
            })
            # wick in the direction of v1 trade (rejection wick)
            if sig == "CALL":
                f["rej_wick"] = f["up_wick"]
            elif sig == "PUT":
                f["rej_wick"] = f["lo_wick"]
            else:
                f["rej_wick"] = None
        feats.append(f)
    return feats


def stats(rows, name, flip=False):
    w = sum(1 for r in rows if r["v1_result"] == "WIN")
    l = sum(1 for r in rows if r["v1_result"] == "LOSS")
    d = len(rows) - w - l
    if flip:
        w, l = l, w
    n = w + l
    wr = 100 * w / n if n else 0
    net = w * 0.8 - l
    flag = "  <-- FLIP?" if (not flip and n >= 100 and wr < 50.0) else ""
    print(f"  {name:34s} n={len(rows):5d} W={w:4d} L={l:4d} D={d:3d} WR={wr:5.2f}% net={net:+8.1f}R{flag}")
    return {"n": len(rows), "wr": wr, "net": net}


def bucket(rows, key, edges, name):
    print(f"--- {name} [{key}] ---")
    for b in range(len(edges) - 1):
        lo, hi = edges[b], edges[b + 1]
        sub = [r for r in rows if r.get(key) is not None and lo <= r[key] < hi]
        if sub:
            stats(sub, f"{lo:g}..{hi:g}")
    print()


def main():
    rows = load()
    feats = replay(rows)

    # ---- verification: exact match with backtest_trades_60s.csv ----
    tr = list(csv.DictReader(open("backtest_trades_60s.csv")))
    mine = [f for f in feats if f["v1_signal"]]
    key = lambda e: e["entry_ts"]
    a = sorted([(f["entry_ts"], f["v1_signal"], f["v1_result"]) for f in mine])
    b = sorted([(float(t["entry_time"]), t["direction"], t["result"]) for t in tr])
    print(f"replay trades={len(a)} csv trades={len(b)} match={a == b}")
    assert a == b, "REPLAY MISMATCH!"
    print("TRAIN trades:", sum(1 for f in mine if f["split"] == "TRAIN"),
          "| HOLDOUT trades:", sum(1 for f in mine if f["split"] == "HOLDOUT"))

    sig = [f for f in mine if f.get("ema9") is not None]
    TRAIN = [f for f in sig if f["split"] == "TRAIN"]
    print(f"\n================ BASELINE (TRAIN) ================")
    stats(TRAIN, "ALL TRAIN")
    stats([f for f in TRAIN if f["v1_module"] == "MOMENTUM"], "MOMENTUM")
    stats([f for f in TRAIN if f["v1_module"] == "REVERSAL"], "REVERSAL")

    for mod in ("MOMENTUM", "REVERSAL"):
        sub = [f for f in TRAIN if f["v1_module"] == mod]
        print(f"\n================ {mod} loser forensics (TRAIN) ================")
        stats([f for f in sub if f["v1_signal"] == "CALL"], "CALL")
        stats([f for f in sub if f["v1_signal"] == "PUT"], "PUT")
        bucket(sub, "pos", [0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.93, 0.96, 0.99, 1.01], "pos zones")
        bucket(sub, "body_ratio", [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01], "body_ratio")
        bucket(sub, "range_atr", [0, 1.2, 1.5, 2.0, 2.5, 3.0, 5.0, 99], "range_atr (impulse size)")
        bucket(sub, "ema_gap_atr", [-99, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 99], "ema_gap_atr signed (trend strength)")
        bucket(sub, "overext_atr", [-99, -2, -1, -0.5, 0, 0.5, 1, 2, 99], "overext_atr signed (close vs EMA9)")
        bucket(sub, "rej_wick", [0, 0.05, 0.1, 0.15, 0.2, 0.3, 1.01], "rejection wick ratio (trade direction)")
        bucket(sub, "mom2_atr", [-99, -2, -1, -0.5, 0, 0.5, 1, 2, 99], "2-candle momentum / ATR")
        # aligned vs against EMA gap sign
        al = [f for f in sub if (f["v1_signal"] == "CALL") == (f["ema_gap_atr"] > 0)]
        ag = [f for f in sub if (f["v1_signal"] == "CALL") != (f["ema_gap_atr"] > 0)]
        stats(al, "trade WITH ema-gap side")
        stats(ag, "trade AGAINST ema-gap side")
        # exhaustion: big impulse + far from EMA, same side
        print()

    # ---- combined exhaustion view (both modules) ----
    print("================ EXHAUSTION combos (TRAIN) ================")
    for name, cond in [
        ("range_atr>=2.5", lambda f: f["range_atr"] >= 2.5),
        ("range_atr>=2.0", lambda f: f["range_atr"] >= 2.0),
        ("|overext|>=1.5", lambda f: abs(f["overext_atr"]) >= 1.5),
        ("|overext|>=1.0", lambda f: abs(f["overext_atr"]) >= 1.0),
        ("rej_wick>=0.15", lambda f: (f["rej_wick"] or 0) >= 0.15),
        ("rej_wick>=0.10", lambda f: (f["rej_wick"] or 0) >= 0.10),
        ("MOM & range_atr>=2.0", lambda f: f["v1_module"] == "MOMENTUM" and f["range_atr"] >= 2.0),
        ("MOM & |overext|>=1.0", lambda f: f["v1_module"] == "MOMENTUM" and abs(f["overext_atr"]) >= 1.0),
        ("MOM & rej_wick>=0.10", lambda f: f["v1_module"] == "MOMENTUM" and (f["rej_wick"] or 0) >= 0.10),
        ("REV & |ema_gap|>=0.5", lambda f: f["v1_module"] == "REVERSAL" and abs(f["ema_gap_atr"]) >= 0.5),
        ("REV & |ema_gap|>=0.3", lambda f: f["v1_module"] == "REVERSAL" and abs(f["ema_gap_atr"]) >= 0.3),
        ("REV & |ema_gap|<0.1", lambda f: f["v1_module"] == "REVERSAL" and abs(f["ema_gap_atr"]) < 0.1),
    ]:
        stats([f for f in TRAIN if cond(f)], name)

    # ---- dead-zone fill test: v1 no-trades with computable pos ----
    print("\n================ DEAD-ZONE FILL test (TRAIN) ================")
    print("(hypothetical: what if we traded v1 no-trade candles?)")
    dead = [f for f in feats if (f["v1_signal"] is None and f.get("ema9") is not None
                                 and f["split"] == "TRAIN" and f["expiry_price"] is not None
                                 and f["v1_reason"] in ("CLOSE_POSITION_OUT_OF_ZONE",))]
    print(f"dead-zone candles: {len(dead)}")
    for name, cond, direc in [
        ("pos 0.85..0.90 -> TREND dir", lambda f: 0.85 < f["pos"] < 0.90, "trend"),
        ("pos 0.85..0.90 -> FADE dir", lambda f: 0.85 < f["pos"] < 0.90, "fade"),
        ("pos <0.60 -> TREND dir", lambda f: f["pos"] < 0.60, "trend"),
        ("pos <0.60 -> FADE dir", lambda f: f["pos"] < 0.60, "fade"),
    ]:
        sub = [f for f in dead if cond(f)]
        w = l = d = 0
        for f in sub:
            trend_call = (f["dir"] == "BULLISH")
            # pos is measured on trend side; matched color guaranteed in this pool
            take_call = trend_call if direc == "trend" else (not trend_call)
            ep = f["expiry_price"]
            en = f["entry_price"]
            if (ep > en if take_call else ep < en):
                w += 1
            elif ep == en:
                d += 1
            else:
                l += 1
        n = w + l
        wr = 100 * w / n if n else 0
        print(f"  {name:34s} n={len(sub):5d} W={w:4d} L={l:4d} D={d:3d} WR={wr:5.2f}% net={w*0.8-l:+8.1f}R")


if __name__ == "__main__":
    main()

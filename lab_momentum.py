#!/usr/bin/env python3
"""
Momentum signal lab: fresh logic, NO EMA-crossing direction (no EMA at all).
Signal at open[i] from candles[..i-1]; 60s expiry; win = expiry price favors
direction; payout 85%, $1 stake. TRAIN/HOLDOUT + Jul/Aug/Sep validation.
"""
import csv
from datetime import datetime, timezone

CSV_FILE = "candles_asset_1861_60s_365d.csv"
PAYOUT = 0.85
STAKE = 1.0
HOLDOUT_START = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
WARM = 25  # uniform warmup for fair comparison (~0.04% of data)


def load():
    rows = []
    with open(CSV_FILE, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"ts": float(r["timestamp"]), "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"])})
    rows.sort(key=lambda c: c["ts"])
    return rows


def features(rows):
    """Precompute per-index (entry i) features from history ..i-1."""
    n = len(rows)
    closes = [c["close"] for c in rows]
    F = [None] * n
    for i in range(1, n):
        k = i - 1
        c = rows[k]
        o, h, l, cc = c["open"], c["high"], c["low"], c["close"]
        rng = h - l
        body = abs(cc - o)
        f = {
            "bull": cc > o, "bear": cc < o,
            "body_ratio": (body / rng) if rng > 0 else 0,
            "range": rng,
            "pos_col": (((cc - l) / rng) if cc >= o else ((h - cc) / rng)) if rng > 0 else 0.5,
            "hour": datetime.fromtimestamp(c["ts"], tz=timezone.utc).hour,
        }
        if i >= 15:
            # ATR14 (SMA-based, no EMA)
            trs = []
            for t in range(i - 14, i):
                cur, prv = rows[t], rows[t - 1]
                trs.append(max(cur["high"] - cur["low"], abs(cur["high"] - prv["close"]),
                               abs(cur["low"] - prv["close"])))
            f["atr"] = sum(trs) / 14
            f["range_atr"] = rng / f["atr"] if f["atr"] > 0 else 0
            # Cutler RSI (SMA-based, no EMA)
            for per in (3, 14):
                diffs = [closes[t] - closes[t - 1] for t in range(i - per, i)]
                ag = sum(d for d in diffs if d > 0) / per
                al = sum(-d for d in diffs if d < 0) / per
                f[f"rsi{per}"] = 100.0 if al == 0 and ag > 0 else (
                    50.0 if al == 0 else 100 - 100 / (1 + ag / al))
        for kk in (1, 2, 3, 5, 10):
            if k - kk >= 0:
                f[f"mom{kk}"] = cc - closes[k - kk]
        for N in (5, 10, 20):
            if k - N >= 0:
                f[f"hh{N}"] = max(rows[t]["high"] for t in range(k - N, k))
                f[f"ll{N}"] = min(rows[t]["low"] for t in range(k - N, k))
        run = 1
        j = k
        while j - 1 >= 0:
            p = rows[j - 1]
            if (p["close"] > p["open"]) == f["bull"] and p["close"] != p["open"] and (cc != o):
                run += 1
                j -= 1
            else:
                break
        f["run"] = run if cc != o else 0
        f["prev_bull"] = rows[k - 1]["close"] > rows[k - 1]["open"] if k - 1 >= 0 else None
        F[i] = f
    return F


def C(f):
    return "CALL" if f["bull"] else ("PUT" if f["bear"] else None)


def S(v):
    return "CALL" if v > 0 else ("PUT" if v < 0 else None)


def keep_atr(f):
    return f.get("atr") and f["atr"] > 0


RULES = [
    # A: candle continuation (no EMA)
    ("A0 color-follow ALL", lambda f: C(f)),
    ("A1 +body>=0.3", lambda f: C(f) if f["body_ratio"] >= 0.3 else None),
    ("A2 +body>=0.5", lambda f: C(f) if f["body_ratio"] >= 0.5 else None),
    ("A3 +range>=1.0atr", lambda f: C(f) if keep_atr(f) and f["range_atr"] >= 1.0 else None),
    ("A4 +range>=1.2atr", lambda f: C(f) if keep_atr(f) and f["range_atr"] >= 1.2 else None),
    ("A5 +pos>=0.6", lambda f: C(f) if f["pos_col"] >= 0.6 else None),
    ("A6 +pos>=0.7", lambda f: C(f) if f["pos_col"] >= 0.7 else None),
    ("A7 body>=0.3+pos>=0.6", lambda f: C(f) if f["body_ratio"] >= 0.3 and f["pos_col"] >= 0.6 else None),
    ("A8 range>=1.0+body>=0.3", lambda f: C(f) if keep_atr(f) and f["range_atr"] >= 1.0 and f["body_ratio"] >= 0.3 else None),
    ("A9 fresh-impulse follow", lambda f: C(f) if f["prev_bull"] is not None and f["bull"] != f["prev_bull"] and (f["bull"] or f["bear"]) else None),
    ("A10 run-continue", lambda f: C(f) if f["prev_bull"] is not None and (f["bull"] == f["prev_bull"]) and (f["bull"] or f["bear"]) else None),
    ("A11 run>=3 ride", lambda f: C(f) if f["run"] >= 3 else None),
    ("A12 run>=2 ride", lambda f: C(f) if f["run"] >= 2 else None),
    # B: close momentum
    ("B1 mom1 sign", lambda f: S(f.get("mom1", 0))),
    ("B2 mom2 sign", lambda f: S(f.get("mom2", 0))),
    ("B3 mom3 sign", lambda f: S(f.get("mom3", 0))),
    ("B5 mom5 sign", lambda f: S(f.get("mom5", 0))),
    ("B10 mom10 sign", lambda f: S(f.get("mom10", 0))),
    ("B2 +|m|>=0.25atr", lambda f: S(f["mom2"]) if keep_atr(f) and abs(f.get("mom2", 0)) >= 0.25 * f["atr"] else None),
    ("B3 +|m|>=0.25atr", lambda f: S(f["mom3"]) if keep_atr(f) and abs(f.get("mom3", 0)) >= 0.25 * f["atr"] else None),
    ("B5 +|m|>=0.25atr", lambda f: S(f["mom5"]) if keep_atr(f) and abs(f.get("mom5", 0)) >= 0.25 * f["atr"] else None),
    ("B5 +|m|>=0.5atr", lambda f: S(f["mom5"]) if keep_atr(f) and abs(f.get("mom5", 0)) >= 0.5 * f["atr"] else None),
    # C: Donchian breakout (close beyond prior N range)
    ("C5 breakout", lambda f, r=None: None),  # placeholder, needs close -> handled below
    # D: RSI (Cutler, no EMA)
    ("D3 rsi3>50", lambda f: ("CALL" if f.get("rsi3", 50) > 50 else ("PUT" if f.get("rsi3", 50) < 50 else None)) if f.get("rsi3") is not None else None),
    ("D3x rsi3 55/45", lambda f: ("CALL" if f["rsi3"] > 55 else ("PUT" if f["rsi3"] < 45 else None)) if f.get("rsi3") is not None else None),
    ("D14 rsi14>50", lambda f: ("CALL" if f.get("rsi14", 50) > 50 else ("PUT" if f.get("rsi14", 50) < 50 else None)) if f.get("rsi14") is not None else None),
    # E: impulse follow (no EMA)
    ("E1 range>=1.5atr follow", lambda f: C(f) if keep_atr(f) and f["range_atr"] >= 1.5 else None),
    ("E2 range>=2.0atr follow", lambda f: C(f) if keep_atr(f) and f["range_atr"] >= 2.0 else None),
    ("E3 range>=1.5+body>=0.5", lambda f: C(f) if keep_atr(f) and f["range_atr"] >= 1.5 and f["body_ratio"] >= 0.5 else None),
]


def breakout_rule(f, cc, N):
    if f.get(f"hh{N}") is None:
        return None
    if cc > f[f"hh{N}"]:
        return "CALL"
    if cc < f[f"ll{N}"]:
        return "PUT"
    return None


def main():
    rows = load()
    F = features(rows)
    n = len(rows)
    BE = 100 / (1 + PAYOUT)
    print(f"payout={PAYOUT*100:.0f}% stake=${STAKE:.0f} breakeven WR={BE:.2f}%")

    # attach closes for breakout rules
    closes = [c["close"] for c in rows]
    rules = [(nm, fn) for nm, fn in RULES if not nm.startswith("C5")]
    rules += [(f"C{N} breakout", (lambda N: (lambda f, i=None, N=N, cc=None: None))(N)) for N in (5, 10, 20)]
    # simpler: handle C rules with explicit closures below
    rules = [(nm, fn) for nm, fn in rules if not nm.startswith("C")]
    for N in (5, 10, 20):
        rules.append((f"C{N} breakout", lambda f, N=N: breakout_rule(f, f["_cc"], N)))
    rules.append(("C10 +range>=1.0atr", lambda f: breakout_rule(f, f["_cc"], 10) if keep_atr(f) and f["range_atr"] >= 1.0 else None))

    for i in range(n):
        if F[i] is not None:
            F[i]["_cc"] = closes[i - 1]

    print(f"\n{'rule':28s} {'TRAIN n':>8s} {'WR':>6s} {'net$':>8s} | {'HO n':>6s} {'WR':>6s} {'net$':>8s} | {'Jul$':>7s} {'Aug$':>7s} {'Sep$':>7s}")
    results = []
    for name, fn in rules:
        buckets = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for i in range(WARM, n - 1):
            f = F[i]
            try:
                d = fn(f)
            except (KeyError, TypeError):
                d = None
            if d is None:
                continue
            en = rows[i]["open"]
            ep = rows[i + 1]["open"]
            r = 0 if (ep > en if d == "CALL" else ep < en) else (2 if ep == en else 1)
            ts = rows[i]["ts"]
            key = "HO" if ts >= HOLDOUT_START else "TR"
            buckets[key][r] += 1
            m = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
            buckets[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][r] += 1

        def stat(b):
            w, l, dr = b[1], b[0], b[2]
            # NOTE: r encoding above: 0=loss? fix: r=0 win? let's recompute cleanly below
            return w, l, dr
        # r: 0 means WIN per ternary? (ep>en...)->0. So index0=win,1=loss,2=draw
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = buckets[k][0], buckets[k][1], buckets[k][2]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT * STAKE - l * STAKE)
        results.append((name, row))
        t, h = row["TR"], row["HO"]
        print(f"{name:28s} {t[0]:8d} {t[1]:5.2f}% {t[2]:+8.1f} | {h[0]:6d} {h[1]:5.2f}% {h[2]:+8.1f} | {row['J'][2]:+7.1f} {row['A'][2]:+7.1f} {row['S'][2]:+7.1f}")

    print("\n== RANK by HOLDOUT net$ (TRAIN net>0 only) ==")
    ok = [(nm, r) for nm, r in results if r["TR"][2] > 0]
    for nm, r in sorted(ok, key=lambda x: -x[1]["HO"][2])[:12]:
        print(f"  {nm:28s} HO ${r['HO'][2]:+.1f} (WR {r['HO'][1]:.2f}% n={r['HO'][0]}) | TRAIN ${r['TR'][2]:+.1f} (WR {r['TR'][1]:.2f}%)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Round 2: fade family (mirror of follow) + v1REV-minus-EMA + combos.
NO EMA anywhere. Payout 85%, $1 stake. TRAIN/HO + Jul/Aug/Sep.
"""
import sys
sys.path.insert(0, ".")
from lab_momentum import load, features, HOLDOUT_START, WARM
from datetime import datetime, timezone

PAYOUT = 0.85


def C(f):
    return "CALL" if f["bull"] else ("PUT" if f["bear"] else None)


def FD(f):
    """fade direction (opposite of candle color)"""
    return "PUT" if f["bull"] else ("CALL" if f["bear"] else None)


def keep_atr(f):
    return f.get("atr") and f["atr"] > 0


def main():
    rows = load()
    F = features(rows)
    n = len(rows)
    closes = [c["close"] for c in rows]
    for i in range(n):
        if F[i] is not None:
            F[i]["_cc"] = closes[i - 1]

    def bo_fade(f, N):  # fade donchian breakout
        if f.get(f"hh{N}") is None:
            return None
        if f["_cc"] > f[f"hh{N}"]:
            return "PUT"
        if f["_cc"] < f[f"ll{N}"]:
            return "CALL"
        return None

    SKIP = {3, 20, 21, 22}
    RULES = [
        ("F0 fade ALL", lambda f: FD(f)),
        ("F1 +body>=0.3", lambda f: FD(f) if f["body_ratio"] >= 0.3 else None),
        ("F2 +body>=0.5", lambda f: FD(f) if f["body_ratio"] >= 0.5 else None),
        ("F3 +range>=1.0atr", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.0 else None),
        ("F4 +range>=1.2atr", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.2 else None),
        ("F4b +range>=1.5atr", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.5 else None),
        ("F5 +pos>=0.6", lambda f: FD(f) if f["pos_col"] >= 0.6 else None),
        ("F6 +pos>=0.7", lambda f: FD(f) if f["pos_col"] >= 0.7 else None),
        ("F6b +pos>=0.8", lambda f: FD(f) if f["pos_col"] >= 0.8 else None),
        ("F6c +pos>=0.9", lambda f: FD(f) if f["pos_col"] >= 0.9 else None),
        ("F7 body.3+pos.6", lambda f: FD(f) if f["body_ratio"] >= 0.3 and f["pos_col"] >= 0.6 else None),
        ("F8 r1.0+b.3+p.6", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.0 and f["body_ratio"] >= 0.3 and f["pos_col"] >= 0.6 else None),
        ("F9 fade fresh-impulse", lambda f: FD(f) if f["prev_bull"] is not None and f["bull"] != f["prev_bull"] and (f["bull"] or f["bear"]) else None),
        ("F10 fade run-continue", lambda f: FD(f) if f["prev_bull"] is not None and (f["bull"] == f["prev_bull"]) and (f["bull"] or f["bear"]) else None),
        ("F11 fade run>=3", lambda f: FD(f) if f["run"] >= 3 else None),
        ("F12 fade run>=2", lambda f: FD(f) if f["run"] >= 2 else None),
        # v1REV-minus-EMA (no trend req, no skip): selective extreme fade
        ("FREV pos.9+r1.2+b.5", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.2 and f["body_ratio"] >= 0.5 and f["pos_col"] >= 0.9 else None),
        ("FREV2 pos.9+r1.5+b.5", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.5 and f["body_ratio"] >= 0.5 and f["pos_col"] >= 0.9 else None),
        ("FREV3 pos.85+r1.2+b.5", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.2 and f["body_ratio"] >= 0.5 and f["pos_col"] >= 0.85 else None),
        ("FREV4 pos.8+r1.2+b.5", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.2 and f["body_ratio"] >= 0.5 and f["pos_col"] >= 0.8 else None),
        ("FREV5 pos.9+r1.0+b.3", lambda f: FD(f) if keep_atr(f) and f["range_atr"] >= 1.0 and f["body_ratio"] >= 0.3 and f["pos_col"] >= 0.9 else None),
        # breakout fades + filters
        ("FC10 fade", lambda f: bo_fade(f, 10)),
        ("FC20 fade", lambda f: bo_fade(f, 20)),
        ("FC20 +pos.7", lambda f: bo_fade(f, 20) if f["pos_col"] >= 0.7 else None),
        ("FC20 +r1.0+b.3", lambda f: bo_fade(f, 20) if keep_atr(f) and f["range_atr"] >= 1.0 and f["body_ratio"] >= 0.3 else None),
        ("FC10 +pos.8", lambda f: bo_fade(f, 10) if f["pos_col"] >= 0.8 else None),
        # RSI fades
        ("FD3 rsi3 80/20", lambda f: ("PUT" if f["rsi3"] >= 80 else ("CALL" if f["rsi3"] <= 20 else None)) if f.get("rsi3") is not None else None),
        ("FD3 rsi3 90/10", lambda f: ("PUT" if f["rsi3"] >= 90 else ("CALL" if f["rsi3"] <= 10 else None)) if f.get("rsi3") is not None else None),
    ]

    print(f"payout=85% stake=$1 breakeven WR=54.05%")
    print(f"\n{'rule':24s} {'TRAIN n':>8s} {'WR':>6s} {'net$':>9s} | {'HO n':>6s} {'WR':>6s} {'net$':>8s} | {'Jul$':>8s} {'Aug$':>8s} {'Sep$':>8s}")
    results = []
    for name, fn in RULES:
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
            buckets["HO" if ts >= HOLDOUT_START else "TR"][r] += 1
            m = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
            buckets[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][r] += 1
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = buckets[k][0], buckets[k][1], buckets[k][2]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l)
        results.append((name, row))
        t, h = row["TR"], row["HO"]
        print(f"{name:24s} {t[0]:8d} {t[1]:5.2f}% {t[2]:+9.1f} | {h[0]:6d} {h[1]:5.2f}% {h[2]:+8.1f} | {row['J'][2]:+8.1f} {row['A'][2]:+8.1f} {row['S'][2]:+8.1f}")

    print("\n== VALIDATED (TRAIN>0 & HO>0), ranked by HO$ ==")
    ok = [(nm, r) for nm, r in results if r["TR"][2] > 0 and r["HO"][2] > 0]
    for nm, r in sorted(ok, key=lambda x: -x[1]["HO"][2]):
        j3 = "3/3" if r["J"][2] > 0 and r["A"][2] > 0 and r["S"][2] > 0 else (
            "2/3" if sum(1 for k in ("J", "A", "S") if r[k][2] > 0) == 2 else "1/3")
        print(f"  {nm:24s} HO ${r['HO'][2]:+8.1f} (WR {r['HO'][1]:5.2f}% n={r['HO'][0]:5d}) | TRAIN ${r['TR'][2]:+8.1f} (WR {r['TR'][1]:5.2f}%) | months {j3}")


if __name__ == "__main__":
    main()

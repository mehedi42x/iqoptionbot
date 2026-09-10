#!/usr/bin/env python3
"""
Separate fix-variants for MaxFade FULL losers. Each judged TRAIN->HO.
Objective: MAXIMUM validated win rate (then profit).
Includes user's EMA-cross-direction variant (V-D) tested fairly.
"""
import sys
sys.path.insert(0, ".")
from lab_momentum import load, features, HOLDOUT_START, WARM
from forensics_mf import ema_full
from datetime import datetime, timezone

PAYOUT = 0.85
SKIP = {3, 20, 21, 22}
WEAK_H = {8, 9, 10, 11, 13, 14}


def build():
    rows = load()
    F = features(rows)
    n = len(rows)
    closes = [c["close"] for c in rows]
    e9 = ema_full(closes, 9)
    e12 = ema_full(closes, 12)
    atrs = [None] * n
    for i in range(15, n):
        trs = []
        for t in range(i - 14, i):
            cur, prv = rows[t], rows[t - 1]
            trs.append(max(cur["high"] - cur["low"], abs(cur["high"] - prv["close"]),
                           abs(cur["low"] - prv["close"])))
        atrs[i] = sum(trs) / 14
    sigs = []
    for i in range(WARM, n - 1):
        f = F[i]
        thr = 0.80 if f["hour"] in SKIP else 0.85
        if f["pos_col"] < thr:
            continue
        d = "PUT" if f["bull"] else ("CALL" if f["bear"] else None)
        if d is None:
            continue
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        r = "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")
        k = i - 1
        ema_side = None
        if e9[k] is not None and e12[k] is not None and e9[k] != e12[k]:
            ema_side = "CALL" if e9[k] > e12[k] else "PUT"
        hist = [a for a in atrs[max(15, i - 60):i] if a]
        m = datetime.fromtimestamp(rows[i]["ts"], tz=timezone.utc).strftime("%Y-%m")
        sigs.append({
            "split": "HO" if rows[i]["ts"] >= HOLDOUT_START else "TR", "month": m,
            "result": r, "dir": d, "pos": f["pos_col"], "hour": f["hour"],
            "skip": f["hour"] in SKIP, "ema_side": ema_side,
            "atr_pct": (sum(1 for a in hist if a < atrs[i]) / len(hist)) if hist and atrs[i] else 0.5,
        })
    return sigs


def score(sigs, keep, direction=None):
    """keep(s)->bool filter; direction(s)->CALL/PUT override or None=fade dir."""
    out = {}
    for sp in ("TR", "HO", "2026-07", "2026-08", "2026-09"):
        sub = [s for s in sigs if (s["split"] == sp if sp in ("TR", "HO") else s["month"] == sp)
               and keep(s)]
        w = l = dr = 0
        for s in sub:
            d = direction(s) if direction else s["dir"]
            r = s["result"]
            if d != s["dir"] and r != "DRAW":
                r = "LOSS" if r == "WIN" else "WIN"
            if r == "WIN":
                w += 1
            elif r == "LOSS":
                l += 1
            else:
                dr += 1
        nn = w + l
        out[sp] = {"n": len(sub), "wr": 100 * w / nn if nn else 0,
                   "net": w * PAYOUT - l}
    return out


def main():
    sigs = build()
    print(f"base signals: {len(sigs)}")
    V = {
        "V-A FULL as-is": (lambda s: True, None),
        "V-B +TRIM weak-hrs": (lambda s: s["hour"] not in WEAK_H, None),
        "V-C pos.90/norm,skip.80": (lambda s: s["pos"] >= (0.80 if s["skip"] else 0.90), None),
        "V-D EMA-cross DIRECTION": (lambda s: s["ema_side"] is not None, lambda s: s["ema_side"]),
        "V-E fade only ALIGNED EMA": (lambda s: s["ema_side"] == s["dir"], None),
        "V-F fade only AGAINST EMA": (lambda s: s["ema_side"] is not None and s["ema_side"] != s["dir"], None),
        "V-G no-storm (atr%<=.75)": (lambda s: (s["atr_pct"] or 0.5) <= 0.75, None),
        "V-H pos>=0.96 only": (lambda s: s["pos"] >= 0.96, None),
        "V-I pos>=0.93 only": (lambda s: s["pos"] >= 0.93, None),
        "V-N FADE_SKIP only": (lambda s: s["skip"], None),
    }
    print(f"\n{'variant':28s} | {'TRAIN n':>7s} {'WR':>6s} {'net$':>8s} | {'HO n':>6s} {'WR':>6s} {'net$':>8s} | {'Jul$':>7s} {'Aug$':>7s} {'Sep$':>7s}")
    res = {}
    for name, (kf, df) in V.items():
        o = score(sigs, kf, df)
        res[name] = o
        t, h = o["TR"], o["HO"]
        print(f"{name:28s} | {t['n']:7d} {t['wr']:5.2f}% {t['net']:+8.1f} | {h['n']:6d} {h['wr']:5.2f}% {h['net']:+8.1f} | "
              f"{o['2026-07']['net']:+7.1f} {o['2026-08']['net']:+7.1f} {o['2026-09']['net']:+7.1f}")
    print("\n== RANK by HO WR (HO n>=300) ==")
    ok = [(nm, r) for nm, r in res.items() if r["HO"]["n"] >= 300]
    for nm, r in sorted(ok, key=lambda x: -x[1]["HO"]["wr"]):
        print(f"  {nm:28s} HO WR {r['HO']['wr']:.2f}% (n={r['HO']['n']}) net ${r['HO']['net']:+.0f} | TRAIN WR {r['TR']['wr']:.2f}% net ${r['TR']['net']:+.0f}")
    print("\n== RANK by HO net$ ==")
    for nm, r in sorted(res.items(), key=lambda x: -x[1]["HO"]["net"]):
        print(f"  {nm:28s} HO ${r['HO']['net']:+.0f} (WR {r['HO']['wr']:.2f}% n={r['HO']['n']})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""COMB Phase 2: HHHL-fix, 2-way cut-hunt (gradient feats), high-WR-add hunt, swap pairing.
Swap PASS: dW>=0 & dL<0 & TR_up & HO_up & 3/3 months green (vs MS2-lab base)."""
import sys
sys.path.insert(0, ".")
from lab_comb import build_ms2, features
from lab_final import build_pool
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

P = 0.85


def feat_allc(allc, rows, bull):
    n = len(rows)
    atr = [None] * n
    for i in range(60, n):
        atr[i] = sum(rows[j]["high"] - rows[j]["low"] for j in range(i - 59, i + 1)) / 60
    F = {}
    for e in allc:
        k = e["i"] - 1
        if k < 1 or k >= n:
            continue
        c = rows[k]
        rng = c["high"] - c["low"]
        body = abs(c["close"] - c["open"])
        bullk = c["close"] > c["open"]
        a = atr[k]
        hi, lo = max(c["close"], c["open"]), min(c["close"], c["open"])
        upw = (c["high"] - hi) / rng if rng > 0 else 0
        low = (lo - c["low"]) / rng if rng > 0 else 0
        run, j = 1, k - 1
        while j >= 0 and (rows[j]["close"] > rows[j]["open"]) == bullk and rows[j]["close"] != rows[j]["open"]:
            run += 1
            j -= 1
        F[e["i"]] = {
            "range_atr": rng / a if a else None,
            "body_atr": body / a if a else None,
            "close_wick": upw if bullk else low,
            "open_wick": low if bullk else upw,
            "atr60": a,
            "runup": abs(c["close"] - rows[j + 1]["open"]) / a if a else None,
        }
    return F


def main():
    ms2, rows = build_ms2()
    features(ms2, rows)
    ms1, allc, rows2, vr, bull, c1 = build_pool()
    F = feat_allc(allc, rows, bull)
    base_idx = {s["i"] for s in ms2}
    tr_atr = sorted(s["atr60"] for s in ms2 if s["atr60"] is not None and s["split"] == "TR")
    a1 = tr_atr[len(tr_atr) // 3]
    print(f"MS2-lab base: n={len(ms2)} | ATR-low cutoff: {a1:.6f}")

    def res60(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def show(name, pool):
        o = []
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            o.append((len(ss), 100 * w / (w + l) if (w + l) else 0, w * P - l, w, l))
        t, h = o[0], o[1]
        flag = ""
        if t[1] < 50 and h[1] < 50 and t[0] >= 200:
            flag = "FLIP?"
        elif t[2] < 0 and h[2] < 0 and t[0] >= 300:
            flag = "CUT?"
        print(f"{flag:5s} {name:30s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f}")
        return o

    print("== HHHL fix ==")
    show("hhll HHHL(up-thrust)", [s for s in ms2 if s["hhll"] == "HHHL"])

    print("\n== 2-way cut-hunt ==")
    cuts = {}
    tests = [
        ("X1 range>1.5 & cw>0.15", lambda s: (s["range_atr"] or 0) > 1.5 and s["close_wick"] > 0.15),
        ("X2 range>1.5 & atr-high", lambda s: (s["range_atr"] or 0) > 1.5 and s["atr60"] is not None and s["atr60"] > tr_atr[2 * len(tr_atr) // 3]),
        ("X3 range>1.5 & body>1", lambda s: (s["range_atr"] or 0) > 1.5 and (s["body_atr"] or 0) > 1.0),
        ("X4 cw>0.15 & atr-high", lambda s: s["close_wick"] > 0.15 and s["atr60"] is not None and s["atr60"] > tr_atr[2 * len(tr_atr) // 3]),
        ("X5 cw>0.15 & bodyr>0.8", lambda s: s["close_wick"] > 0.15 and s["body_ratio"] > 0.8),
        ("X6 body>1 & atr-high", lambda s: (s["body_atr"] or 0) > 1.0 and s["atr60"] is not None and s["atr60"] > tr_atr[2 * len(tr_atr) // 3]),
        ("X7 range>2 & cw>0.1", lambda s: (s["range_atr"] or 0) > 2.0 and s["close_wick"] > 0.1),
        ("X8 HHHL & range>1.5", lambda s: s["hhll"] == "HHHL" and (s["range_atr"] or 0) > 1.5),
    ]
    for nm, cond in tests:
        pool = [s for s in ms2 if cond(s)]
        o = show(nm, pool)
        if o[0][2] < 0 and o[1][2] < 0 and o[0][0] >= 300:
            cuts[nm] = pool

    print("\n== high-WR-add hunt (untraded pool) ==")
    NW = lambda e: not e["weak"] and not e["skip"]
    adds = {}
    adefs = [
        ("A1 atr-low .85-.90", lambda e, f: NW(e) and f["atr60"] is not None and f["atr60"] < a1 and 0.85 <= e["pos"] < 0.90),
        ("A2 small-range .85-.90", lambda e, f: NW(e) and f["range_atr"] is not None and f["range_atr"] < 1.0 and 0.85 <= e["pos"] < 0.90),
        ("A3 cw-small .85-.90", lambda e, f: NW(e) and f["close_wick"] < 0.05 and 0.85 <= e["pos"] < 0.90),
        ("A4 ow-big .85-.90", lambda e, f: NW(e) and f["open_wick"] > 0.15 and 0.85 <= e["pos"] < 0.90),
        ("A5 small-body .90-.93", lambda e, f: NW(e) and f["body_atr"] is not None and f["body_atr"] < 0.6 and 0.90 <= e["pos"] < 0.93),
        ("A6 fresh-run .85-.90", lambda e, f: NW(e) and f["runup"] is not None and f["runup"] < 1.0 and 0.85 <= e["pos"] < 0.90),
    ]
    for nm, cond in adefs:
        pool = []
        for e in allc:
            if e["i"] in base_idx or e["flat"] or e["doji"] or e["i"] not in F:
                continue
            if not cond(e, F[e["i"]]):
                continue
            d = "PUT" if e["bull"] else "CALL"
            pool.append({"i": e["i"], "ts": e["ts"], "hour": e["hour"], "pos": e["pos"], "dir": d,
                         "result": res60(e["i"], d), "split": "HO" if e["ts"] >= HOLDOUT_START else "TR"})
        o = show(nm, pool)
        # months
        mo = {}
        for s in pool:
            m = datetime.fromtimestamp(s["ts"], tz=timezone.utc).strftime("%Y-%m")
            w = 1 if s["result"] == "WIN" else 0
            l = 1 if s["result"] == "LOSS" else 0
            mo[m] = (mo.get(m, (0, 0))[0] + w, mo.get(m, (0, 0))[1] + l)
        ms = " ".join(f"{k[5:]}:{v[0]*P-v[1]:+.1f}" for k, v in sorted(mo.items()))
        ok = o[0][2] > 0 and o[1][2] > 0 and all(v[0] * P - v[1] > 0 for v in mo.values())
        print(f"      months: {ms} | {'VALIDATED-ADD' if ok else 'reject'}")
        if ok:
            adds[nm] = pool

    print(f"\n== swap pairing ({len(cuts)} cuts x {len(adds)} adds) ==")
    B = {}
    for sp in ("TR", "HO", "FULL"):
        ss = ms2 if sp == "FULL" else [s for s in ms2 if s["split"] == sp]
        w = sum(1 for s in ss if s["result"] == "WIN")
        l = sum(1 for s in ss if s["result"] == "LOSS")
        B[sp] = (w, l, w * P - l)
    for cn, cp in cuts.items():
        cidx = {s["i"] for s in cp}
        for an, ap in adds.items():
            pool = [s for s in ms2 if s["i"] not in cidx] + ap
            S = {}
            for sp in ("TR", "HO", "FULL"):
                ss = pool if sp == "FULL" else [x for x in pool if x["split"] == sp]
                w = sum(1 for x in ss if x["result"] == "WIN")
                l = sum(1 for x in ss if x["result"] == "LOSS")
                S[sp] = (w, l, w * P - l)
            dW = S["FULL"][0] - B["FULL"][0]
            dL = S["FULL"][1] - B["FULL"][1]
            dTR = S["TR"][2] - B["TR"][2]
            dHO = S["HO"][2] - B["HO"][2]
            w, l = S["FULL"][0], S["FULL"][1]
            ok = dW >= 0 and dL < 0 and dTR > 0 and dHO > 0
            print(f"{'✅PASS' if ok else '❌FAIL'} {cn}+{an}: n={len(pool)} WR={100*w/(w+l):.2f}% | dW={dW:+d} dL={dL:+d} dTR={dTR:+.1f} dHO={dHO:+.1f}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""GRAND ASSAULT: volume deep-dive + sniper ladder + preserving assault.
Sniper bars: FULL n>=1000, HO n>=150, 3/3 green, HO-WR>60.25. Rank by HO-WR.
Swap bars (S9b): dW>=0 & dL<0 & TR_up & HO_up vs MS2-lab."""
import sys, csv
sys.path.insert(0, ".")
from lab_comb import build_ms2, features
from lab_regime import compute_feats
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

P = 0.85


def main():
    ms2, rows = build_ms2()
    features(ms2, rows)
    vr, bull = compute_feats(rows)
    volmap = {}
    with open("candles_asset_1861_60s_365d.csv") as f:
        for r in csv.DictReader(f):
            volmap[float(r["timestamp"])] = float(r["volume"])
    vols = [volmap.get(r["ts"]) for r in rows]
    for s in ms2:
        k = s["i"] - 1
        s["trend"] = bull[k]
        s["withT"] = (s["trend"] == 1 and s["dir"] == "CALL") or (s["trend"] == -1 and s["dir"] == "PUT")
        if k >= 60 and all(x is not None for x in vols[k - 59:k + 1]):
            v5 = sum(vols[k - 4:k + 1]) / 5
            v60 = sum(vols[k - 59:k + 1]) / 60
            vpast = sum(vols[k - 9:k - 4]) / 5
            s["volr"] = v5 / v60 if v60 > 0 else None
            s["volraw"] = vols[k]
            s["voltrend"] = v5 / vpast if vpast > 0 else None
        else:
            s["volr"] = s["volraw"] = s["voltrend"] = None
    W = sum(1 for s in ms2 if s["result"] == "WIN")
    L = sum(1 for s in ms2 if s["result"] == "LOSS")
    print(f"MS2-lab base: n={len(ms2)} W={W} L={L} WR={100*W/(W+L):.2f}%")
    tr_atr = sorted(s["atr60"] for s in ms2 if s["atr60"] is not None and s["split"] == "TR")
    a2 = tr_atr[2 * len(tr_atr) // 3]
    trvol = sorted(s["volr"] for s in ms2 if s["volr"] is not None and s["split"] == "TR")
    q1, q2 = trvol[len(trvol) // 3], trvol[2 * len(trvol) // 3]
    trvr = sorted(s["volraw"] for s in ms2 if s["volraw"] is not None and s["split"] == "TR")
    r1, r2 = trvr[len(trvr) // 3], trvr[2 * len(trvr) // 3]
    print(f"cutoffs atr-hi>{a2:.6f} volr {q1:.2f}/{q2:.2f} volraw {r1:.0f}/{r2:.0f}")

    def show(name, pool, flag=True):
        o = []
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            o.append((len(ss), 100 * w / nn if nn else 0, w * P - l, w, l))
        t, h = o[0], o[1]
        fl = ""
        if flag:
            if t[1] < 50 and h[1] < 50 and t[0] >= 200:
                fl = "FLIP?"
            elif t[2] < 0 and h[2] < 0 and t[0] >= 300:
                fl = "CUT?"
        print(f"{fl:5s} {name:30s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f}")
        return o

    print("\n== PART 1: volume assault ==")
    V = [
        ("V1a volr-hi+range>1.5", lambda s: s["volr"] is not None and s["volr"] > q2 and (s["range_atr"] or 0) > 1.5),
        ("V1b volr-hi+cw>0.15", lambda s: s["volr"] is not None and s["volr"] > q2 and s["close_wick"] > 0.15),
        ("V1c volr-hi+body>1", lambda s: s["volr"] is not None and s["volr"] > q2 and (s["body_atr"] or 0) > 1.0),
        ("V1d volr-lo+range<1", lambda s: s["volr"] is not None and s["volr"] < q1 and (s["range_atr"] or 9) < 1.0),
        ("V2a volraw-low", lambda s: s["volraw"] is not None and s["volraw"] < r1),
        ("V2b volraw-mid", lambda s: s["volraw"] is not None and r1 <= s["volraw"] <= r2),
        ("V2c volraw-high", lambda s: s["volraw"] is not None and s["volraw"] > r2),
        ("V3a vol-rising", lambda s: s["voltrend"] is not None and s["voltrend"] > 1.3),
        ("V3b vol-falling", lambda s: s["voltrend"] is not None and s["voltrend"] < 0.77),
        ("V4a skip+volr-hi", lambda s: s["skip"] and s["volr"] is not None and s["volr"] > q2),
        ("V4b normal+volr-hi", lambda s: not s["skip"] and s["volr"] is not None and s["volr"] > q2),
    ]
    for nm, cond in V:
        show(nm, [s for s in ms2 if cond(s)])

    print("\n== PART 2: sniper ladder (cumulative cuts) ==")
    def sniper(name, cond):
        pool = [s for s in ms2 if cond(s)]
        o = show(name, pool, flag=False)
        t, h = o[0], o[1]
        mo = {}
        for s in pool:
            m = datetime.fromtimestamp(s["ts"], tz=timezone.utc).strftime("%Y-%m")
            mo.setdefault(m, [0, 0])
            mo[m][0 if s["result"] == "WIN" else 1] += 1 if s["result"] in ("WIN", "LOSS") else 0
        ms = " ".join(f"{k[5:]}:{v[0]*P-v[1]:+.1f}" for k, v in sorted(mo.items()))
        ok = (t[0] + h[0] >= 1000 and h[0] >= 150 and h[1] > 60.25
              and all(v[0] * P - v[1] > 0 for v in mo.values()))
        w, l = t[3] + h[3], t[4] + h[4]
        print(f"      {'✅SNIPER' if ok else '❌'} FULL n={t[0]+h[0]} WR={100*w/(w+l):.2f}% net={t[2]+h[2]:+.1f} | months {ms}")
        return pool if ok else None

    rng_ok = lambda s: (s["range_atr"] or 0) <= 1.5
    cw_ok = lambda s: s["close_wick"] <= 0.15
    atr_ok = lambda s: s["atr60"] is not None and s["atr60"] <= a2
    body_ok = lambda s: (s["body_atr"] or 0) <= 1.0
    noWithT = lambda s: not s["withT"]
    sniper("SNL-0 skip-only", lambda s: s["skip"])
    sniper("SNL-1 -range>1.5", rng_ok)
    sniper("SNL-2 -cw>0.15", lambda s: rng_ok(s) and cw_ok(s))
    sniper("SNL-3 -atr-high", lambda s: rng_ok(s) and cw_ok(s) and atr_ok(s))
    sniper("SNL-4 -body>1", lambda s: rng_ok(s) and cw_ok(s) and atr_ok(s) and body_ok(s))
    sniper("SNL-5 -withT", lambda s: rng_ok(s) and cw_ok(s) and atr_ok(s) and body_ok(s) and noWithT(s))
    sniper("SNL-7 hour-sniper", lambda s: s["hour"] in (2, 4, 19, 21, 22, 23))
    print("\n== PART 4: intersections ==")
    sniper("SNI-1 skip+calm+small", lambda s: s["skip"] and (s["range_atr"] or 9) < 1.0)
    sniper("SNI-2 h21/22+small", lambda s: s["hour"] in (21, 22) and (s["range_atr"] or 9) < 1.0)


if __name__ == "__main__":
    main()

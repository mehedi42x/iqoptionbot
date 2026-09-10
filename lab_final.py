#!/usr/bin/env python3
"""FINAL bake-off: 12 loser-cutting strategies vs MS1 base.
PASS = winners NOT down (dW>=0) AND losers down (dL<0) AND TR_net up AND HO_net up.
net in $10/trade. Base = MS1-lab pool."""
import sys, csv
sys.path.insert(0, ".")
from lab_regime import compute_feats, WARM
from forensics_mfv2 import build_v2
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

WIN10, LOSS10 = 8.5, 10.0


def build_pool():
    sigs, allc, rows = build_v2()
    vr, bull = compute_feats(rows)
    tr_vr = sorted(v for e in allc for v in [vr[e["i"] - 1]] if v is not None and e["ts"] < HOLDOUT_START)
    c1 = tr_vr[int(len(tr_vr) * 0.33)]

    def res60(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    ms1 = []
    for s in sigs:
        ms1.append({"i": s["i"], "ts": s["ts"], "hour": s["hour"], "pos": s.get("pos"), "dir": s["dir"],
                    "result": s["result"], "split": s["split"], "skip": s.get("skip", False)})
    have = {s["i"] for s in sigs}
    for e in allc:
        if e["i"] in have or e["flat"] or e["doji"]:
            continue
        f1a = (not e["weak"] and not e["skip"] and e["hour"] in (19, 23) and 0.90 <= e["pos"] < 0.93)
        m2 = (e["hour"] in (20, 21, 22) and (e["i"] - 1) >= WARM and vr[e["i"] - 1] is not None
              and vr[e["i"] - 1] < c1 and 0.75 <= e["pos"] < 0.80)
        if not (f1a or m2):
            continue
        d = "PUT" if e["bull"] else "CALL"
        ms1.append({"i": e["i"], "ts": e["ts"], "hour": e["hour"], "pos": e["pos"], "dir": d,
                    "result": res60(e["i"], d), "split": "HO" if e["ts"] >= HOLDOUT_START else "TR",
                    "skip": e["skip"]})
    ms1.sort(key=lambda s: s["i"])
    # volume by ts
    volmap = {}
    with open("candles_asset_1861_60s_365d.csv") as f:
        for r in csv.DictReader(f):
            volmap[float(r["timestamp"])] = float(r["volume"])
    vols = [volmap.get(r["ts"]) for r in rows]
    for s in ms1:
        dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
        s["wd"] = dt.strftime("%a")
        s["day"] = dt.strftime("%Y-%m-%d")
        k = s["i"] - 1
        s["trend"] = bull[k] if k < len(bull) else None
        v = vr[k] if k < len(vr) else None
        s["vr"] = v
        s["vreg"] = "calm" if v is not None and v < c1 else ("storm" if v is not None and v > 1.058 else ("normal" if v is not None else None))
        s["vrslope"] = (vr[k] - vr[k - 5]) if k >= 65 and vr[k] is not None and vr[k - 5] is not None else None
        s["prev_doji"] = (rows[k - 1]["open"] == rows[k - 1]["close"]) if k >= 1 else False
        # volume ratio vol5/vol60 of signal candle
        if k >= 60 and all(x is not None for x in vols[k - 59:k + 1]):
            v5 = sum(vols[k - 4:k + 1]) / 5
            v60 = sum(vols[k - 59:k + 1]) / 60
            s["volr"] = v5 / v60 if v60 > 0 else None
        else:
            s["volr"] = None
    return ms1, allc, rows, vr, bull, c1


def stats(pool, base=None):
    o = {}
    for sp in ("TR", "HO", "FULL"):
        ss = pool if sp == "FULL" else [s for s in pool if s["split"] == sp]
        w = sum(1 for s in ss if s["result"] == "WIN")
        l = sum(1 for s in ss if s["result"] == "LOSS")
        o[sp] = (w, l, len(ss) - w - l, w * WIN10 - l * LOSS10)
    return o


def verdict(name, pool, B, extra=""):
    S = stats(pool)
    dW = S["FULL"][0] - B["FULL"][0]
    dL = S["FULL"][1] - B["FULL"][1]
    dTR = S["TR"][3] - B["TR"][3]
    dHO = S["HO"][3] - B["HO"][3]
    w, l, d, net = S["FULL"]
    wr = 100 * w / (w + l)
    ok = dW >= 0 and dL < 0 and dTR > 0 and dHO > 0
    tag = "✅PASS" if ok else "❌FAIL"
    why = []
    if dW < 0:
        why.append(f"W{dW:+d}")
    if dL >= 0:
        why.append(f"L{dL:+d}")
    if dTR <= 0:
        why.append("TR↓")
    if dHO <= 0:
        why.append("HO↓")
    print(f"{tag} {name:28s} n={len(pool):5d} WR={wr:5.2f}% net@10=${net:+10.1f} | dW={dW:+5d} dL={dL:+5d} dTR=${dTR:+8.1f} dHO=${dHO:+7.1f} | {'OK' if ok else ','.join(why)} {extra}")
    return ok, dW, dL, dTR, dHO


def main():
    ms1, allc, rows, vr, bull, c1 = build_pool()
    B = stats(ms1)
    print(f"BASE MS1-lab: n={len(ms1)} W={B['FULL'][0]} L={B['FULL'][1]} WR={100*B['FULL'][0]/(B['FULL'][0]+B['FULL'][1]):.2f}% net@10=${B['FULL'][3]:,.1f} (TR ${B['TR'][3]:,.1f} / HO ${B['HO'][3]:,.1f})")

    # S1/S2: cooldown after loss
    for K, nm in ((1, "S1 cooldown-1"), (2, "S2 cooldown-2")):
        pool, skip = [], 0
        for s in ms1:
            if skip > 0:
                skip -= 1
                continue
            pool.append(s)
            if s["result"] == "LOSS":
                skip = K
        verdict(nm, pool, B)

    # S3: daily stop-loss ($1-scale levels)
    byday = {}
    for s in ms1:
        byday.setdefault(s["day"], []).append(s)
    for X in (3, 5, 10):
        pool = []
        for d in sorted(byday):
            eq = 0
            for s in byday[d]:
                if eq <= -X:
                    continue
                pool.append(s)
                eq += 0.85 if s["result"] == "WIN" else (-1 if s["result"] == "LOSS" else 0)
        verdict(f"S3 dailySL-1 compression".replace("1 compression", f"${X}"), pool, B, "(live-feasible)")

    # S5: per-hour forensics
    print("\n== S5 per-hour (MS1 pool) ==")
    for h in range(24):
        for sp in ("TR", "HO"):
            ss = [s for s in ms1 if s["hour"] == h and s["split"] == sp]
            if not ss:
                continue
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            print(f"  h={h:02d} {sp}: n={len(ss):4d} WR={100*w/nn if nn else 0:5.2f}% ${w*WIN10-l*LOSS10:+8.1f}")

    # S6/S10/S11/S12: feature filters
    verdict("S6 vr-slope>0.25 skip", [s for s in ms1 if not (s["vrslope"] is not None and s["vrslope"] > 0.25)], B)
    verdict("S10 vr>1.5 skip", [s for s in ms1 if not (s["vr"] is not None and s["vr"] > 1.5)], B)
    verdict("S11 post-doji skip", [s for s in ms1 if not s["prev_doji"]], B)
    verdict("S12 nonskip bar 0.94", [s for s in ms1 if s["skip"] or (s["pos"] is not None and s["pos"] >= 0.94)], B)

    # S9 swaps: need add-leg exact pools from allc
    def res60(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def addpool(cond):
        out = []
        for e in allc:
            if e["flat"] or e["doji"] or not cond(e):
                continue
            d = "PUT" if e["bull"] else "CALL"
            out.append({"i": e["i"], "ts": e["ts"], "hour": e["hour"], "pos": e["pos"], "dir": d,
                        "result": res60(e["i"], d), "split": "HO" if e["ts"] >= HOLDOUT_START else "TR", "skip": e["skip"]})
        return out

    def reg_calm(e):
        v = vr[e["i"] - 1]
        return v is not None and v < c1

    D2 = addpool(lambda e: not e["weak"] and not e["skip"] and reg_calm(e) and 0.85 <= e["pos"] < 0.90)
    F2bX = addpool(lambda e: e["hour"] in (20, 21, 22) and 0.75 <= e["pos"] < 0.80 and not (reg_calm(e) and (e["i"] - 1) >= WARM))
    # F2bX excludes M2-overlap (calm+warmed); non-calm needs vr known:
    F2bX = [s for s in F2bX if vr[s["i"] - 1] is not None]
    G3 = addpool(lambda e: not e["weak"] and not e["skip"] and (e.get("body_atr") or 9) < 0.3 and 0.85 <= e["pos"] < 0.93)
    base_idx = {s["i"] for s in ms1}
    D2 = [s for s in D2 if s["i"] not in base_idx]
    F2bX = [s for s in F2bX if s["i"] not in base_idx]
    G3 = [s for s in G3 if s["i"] not in base_idx]
    for nm, p in (("D2", D2), ("F2bX", F2bX), ("G3", G3)):
        S = stats(p)
        print(f"  add-leg {nm}: n={len(p)} W={S['FULL'][0]} L={S['FULL'][1]} TR=${S['TR'][3]:+.1f} HO=${S['HO'][3]:+.1f}")

    def withT(s):
        return (s["trend"] == 1 and s["dir"] == "CALL") or (s["trend"] == -1 and s["dir"] == "PUT")

    cuts = {
        "L8": lambda s: s["wd"] == "Fri" and s["hour"] in (12, 13, 14, 15),
        "L3": lambda s: s["hour"] in (12, 15),
        "M3": lambda s: (not s["skip"]) and withT(s) and s["pos"] is not None and 0.93 <= s["pos"] < 0.94,
        "N9": lambda s: (not s["skip"]) and s["vreg"] == "storm" and s["pos"] is not None and 0.93 <= s["pos"] < 0.96,
    }
    for nm, (cn, add) in (("S9a L8+D2", ("L8", D2)), ("S9b L3+D2", ("L3", D2)),
                           ("S9c M3+F2bX", ("M3", F2bX)), ("S9d N9+G3", ("N9", G3))):
        pool = [s for s in ms1 if not cuts[cn](s)] + add
        verdict(nm, pool, B)

    # S13: 1H alignment (descriptive + flip-flag)
    print("\n== S13 1H-trend alignment ==")
    b1 = {}
    for i, r in enumerate(rows):
        b1.setdefault(int(r["ts"]) // 3600, []).append(i)
    k1 = sorted(b1.keys())
    c1h = {b: rows[b1[b][-1]]["close"] for b in k1}
    st = {}
    for bi, b in enumerate(k1):
        if bi >= 50:
            prev = [c1h[k1[k]] for k in range(bi - 50, bi + 1)]
            s50 = sum(prev[-50:]) / 50
            s20 = sum(prev[-20:]) / 20
            c = c1h[b]
            st[b] = 1 if (c > s50 and s20 > s50) else (-1 if (c < s50 and s20 < s50) else 0)

    def h1(s):
        return st.get(int(s["ts"]) // 3600 - 1)

    for nm, cond in (("1H withT", lambda s: (h1(s) == 1 and s["dir"] == "CALL") or (h1(s) == -1 and s["dir"] == "PUT")),
                     ("1H vsT", lambda s: (h1(s) == 1 and s["dir"] == "PUT") or (h1(s) == -1 and s["dir"] == "CALL")),
                     ("1H flat/unk", lambda s: h1(s) in (0, None))):
        pool = [s for s in ms1 if cond(s)]
        S = stats(pool)
        for sp in ("TR", "HO"):
            w, l, d, net = S[sp]
            nn = w + l
            print(f"  {nm:12s} {sp}: n={w+l+d:5d} WR={100*w/nn if nn else 0:5.2f}% ${net:+9.1f}")

    # S14: volume forensics (research-only: live volume unverified)
    print("\n== S14 volume ratio (RESEARCH ONLY) ==")
    trvol = sorted(s["volr"] for s in ms1 if s["volr"] is not None and s["split"] == "TR")
    if trvol:
        q1, q2 = trvol[len(trvol) // 3], trvol[2 * len(trvol) // 3]
        print(f"  vol terciles (TRAIN): {q1:.2f}/{q2:.2f}")
        for nm, cond in (("vol low", lambda s: s["volr"] is not None and s["volr"] < q1),
                         ("vol mid", lambda s: s["volr"] is not None and q1 <= s["volr"] <= q2),
                         ("vol high", lambda s: s["volr"] is not None and s["volr"] > q2),
                         ("vol spike>2", lambda s: s["volr"] is not None and s["volr"] > 2.0),
                         ("vol drought<.5", lambda s: s["volr"] is not None and s["volr"] < 0.5)):
            pool = [s for s in ms1 if cond(s)]
            S = stats(pool)
            for sp in ("TR", "HO"):
                w, l, d, net = S[sp]
                nn = w + l
                print(f"  {nm:14s} {sp}: n={w+l+d:5d} WR={100*w/nn if nn else 0:5.2f}% ${net:+9.1f}")


if __name__ == "__main__":
    main()

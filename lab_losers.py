#!/usr/bin/env python3
"""Loser-to-winner hunt on MS1 pool (11,078) + $10 accounting.
FLIP bar: BOTH splits <50% (n_TR>=200). FILTER bar: removes losers, ~0 winners lost.
EXPIRY research: @120s vs @60s per regime (deploy needs bot change — research only)."""
import sys
sys.path.insert(0, ".")
from lab_regime import compute_feats, WARM
from forensics_mfv2 import build_v2
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

PAYOUT = 0.85
STAKE = 10.0
WIN10 = 8.5


def main():
    sigs, allc, rows = build_v2()
    vr, bull = compute_feats(rows)
    tr_vr = sorted(v for e in allc for v in [vr[e["i"] - 1]] if v is not None and e["ts"] < HOLDOUT_START)
    c1 = tr_vr[int(len(tr_vr) * 0.33)]
    print(f"calm cutoff (frozen): {c1:.3f}")

    def res60(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def res120(i, d):
        if i + 2 >= len(rows):
            return None
        en = rows[i]["open"]
        ep = rows[i + 2]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    # MS1 pool = v2 + F1a + M2
    ms1 = list(sigs)
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
                    "skip": e["skip"], "weak": e["weak"], "body_atr": e.get("body_atr"),
                    "range_pct": e.get("range_pct"), "run": e.get("run")})
    ms1.sort(key=lambda s: s["i"])
    for s in ms1:
        dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
        s["min"] = dt.minute
        s["wd"] = dt.strftime("%a")
        s["trend"] = bull[s["i"] - 1]
        v = vr[s["i"] - 1]
        s["vreg"] = "calm" if v is not None and v < c1 else ("storm" if v is not None and v > 1.058 else ("normal" if v is not None else None))
    W = sum(1 for s in ms1 if s["result"] == "WIN")
    L = sum(1 for s in ms1 if s["result"] == "LOSS")
    D = len(ms1) - W - L
    print(f"MS1-lab pool: n={len(ms1)} W={W} L={L} D={D} WR={100*W/(W+L):.2f}% net@10=${W*WIN10-L*STAKE:,.1f}")

    def show(name, pool):
        out = []
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            dr = len(ss) - w - l
            nn = w + l
            out.append((len(ss), 100 * w / nn if nn else 0, w * WIN10 - l * STAKE, w, l, dr))
        t, h = out[0], out[1]
        flip = "FLIP?" if (t[1] < 50 and h[1] < 50 and t[0] >= 200) else "    "
        print(f"{flip} {name:26s} | TR n={t[0]:5d} {t[1]:5.2f}% ${t[2]:+9.1f} (W{t[3]}/L{t[4]}/D{t[5]}) | HO n={h[0]:4d} {h[1]:5.2f}% ${h[2]:+8.1f} (W{h[3]}/L{h[4]}/D{h[5]})")
        return out

    print("\n== sequence (prev-signal result) ==")
    prev = {}
    last = None
    for s in ms1:
        prev[s["i"]] = last
        last = s["result"]
    show("after WIN", [s for s in ms1 if prev[s["i"]] == "WIN"])
    show("after LOSS", [s for s in ms1 if prev[s["i"]] == "LOSS"])
    show("after DRAW", [s for s in ms1 if prev[s["i"]] == "DRAW"])
    prev2 = {}
    seq = [s["result"] for s in ms1]
    for k, s in enumerate(ms1):
        prev2[s["i"]] = seq[k - 2] if k >= 2 else None
    show("after 2 LOSS", [s for s in ms1 if prev[s["i"]] == "LOSS" and prev2[s["i"]] == "LOSS"])

    print("\n== structural slices ==")
    show("L3 h12/15 all", [s for s in ms1 if s["hour"] in (12, 15)])
    show("L4 top-of-hour m0-1", [s for s in ms1 if s["min"] in (0, 1)])
    show("L5 body>=2atr", [s for s in ms1 if s.get("body_atr") is not None and s["body_atr"] >= 2.0])
    show("L6 range%60>0.95", [s for s in ms1 if s.get("range_pct") is not None and s["range_pct"] > 0.95])
    show("L7 storm+withT", [s for s in ms1 if s["vreg"] == "storm" and ((s["trend"] == 1 and s["dir"] == "CALL") or (s["trend"] == -1 and s["dir"] == "PUT"))])
    show("L8 Fri h12-15", [s for s in ms1 if s["wd"] == "Fri" and s["hour"] in (12, 13, 14, 15)])
    show("L9 Sun all", [s for s in ms1 if s["wd"] == "Sun"])
    show("L10 skip h=3 all", [s for s in ms1 if s["hour"] == 3])

    print("\n== expiry research: @120 vs @60 (same subset) ==")
    def show_exp(name, pool):
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            w60 = l60 = w12 = l12 = 0
            for s in ss:
                r60 = s["result"]
                r12 = res120(s["i"], s["dir"])
                if r12 is None:
                    continue
                if r60 == "WIN":
                    w60 += 1
                elif r60 == "LOSS":
                    l60 += 1
                if r12 == "WIN":
                    w12 += 1
                elif r12 == "LOSS":
                    l12 += 1
            n60 = w60 + l60
            n12 = w12 + l12
            dW = w12 - w60
            dN = (w12 * WIN10 - l12 * STAKE) - (w60 * WIN10 - l60 * STAKE)
            print(f"  {name:16s} {sp}: @60 {100*w60/n60 if n60 else 0:5.2f}% ${w60*WIN10-l60*STAKE:+9.1f} | @120 {100*w12/n12 if n12 else 0:5.2f}% ${w12*WIN10-l12*STAKE:+9.1f} | dW={dW:+5d} dNet=${dN:+9.1f}")
    show_exp("storm", [s for s in ms1 if s["vreg"] == "storm"])
    show_exp("calm", [s for s in ms1 if s["vreg"] == "calm"])
    show_exp("withT", [s for s in ms1 if (s["trend"] == 1 and s["dir"] == "CALL") or (s["trend"] == -1 and s["dir"] == "PUT")])
    show_exp("vsT", [s for s in ms1 if (s["trend"] == 1 and s["dir"] == "PUT") or (s["trend"] == -1 and s["dir"] == "CALL")])
    show_exp("skip", [s for s in ms1 if s["skip"]])
    show_exp("h12/15", [s for s in ms1 if s["hour"] in (12, 15)])


if __name__ == "__main__":
    main()

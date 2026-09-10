#!/usr/bin/env python3
"""COMB Phase 3: day-context features (day-range regime, day-extreme position,
cluster-first vs continuation) + auto-swap with validated adds (A1/D2/G3).
Swap PASS: dW>=0 & dL<0 & TR_up & HO_up (vs MS2-lab base)."""
import sys
sys.path.insert(0, ".")
from lab_comb import build_ms2, features
from lab_final import build_pool
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

P = 0.85


def main():
    ms2, rows = build_ms2()
    features(ms2, rows)
    ms1, allc, rows2, vr, bull, c1 = build_pool()
    base_idx = {s["i"] for s in ms2}
    tr_atr = sorted(s["atr60"] for s in ms2 if s["atr60"] is not None and s["split"] == "TR")
    a1 = tr_atr[len(tr_atr) // 3]

    # day-so-far high/low per row
    dayhi, daylo, curday = {}, {}, None
    for i, r in enumerate(rows):
        d = datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        if d != curday:
            curday, dh, dl = d, r["high"], r["low"]
        dh = max(dh, r["high"])
        dl = min(dl, r["low"])
        dayhi[i], daylo[i] = dh, dl

    for s in ms2:
        k = s["i"] - 1
        a = s["atr60"]
        s["dayrange"] = (dayhi[k] - daylo[k]) / a if a else None
        cc = rows[k]["close"]
        s["dpos"] = ("high" if (dayhi[k] - cc) / a < 0.2 else ("low" if (cc - daylo[k]) / a < 0.2 else "mid")) if a else "mid"
    # cluster flags (ordered by i)
    for j, s in enumerate(ms2):
        if j == 0:
            s["first"] = True
        else:
            p = ms2[j - 1]
            s["first"] = (s["i"] - p["i"] > 10) or (p["dir"] != s["dir"])

    def show(name, pool):
        o = []
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            o.append((len(ss), 100 * w / nn if nn else 0, w * P - l, w, l))
        t, h = o[0], o[1]
        flag = ""
        if t[1] < 50 and h[1] < 50 and t[0] >= 200:
            flag = "FLIP?"
        elif t[2] < 0 and h[2] < 0 and t[0] >= 300:
            flag = "CUT?"
        print(f"{flag:5s} {name:26s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f}")
        return o

    print("== W1 day-range regime ==")
    for nm, cond in (("dayrange<1.5", lambda s: s["dayrange"] is not None and s["dayrange"] < 1.5),
                     ("dayrange 1.5-3", lambda s: s["dayrange"] is not None and 1.5 <= s["dayrange"] <= 3.0),
                     ("dayrange>3", lambda s: s["dayrange"] is not None and s["dayrange"] > 3.0)):
        show(nm, [s for s in ms2 if cond(s)])
    print("== W3 day-extreme position ==")
    for nm in ("high", "mid", "low"):
        show(f"dpos {nm}", [s for s in ms2 if s["dpos"] == nm])
    print("== W6 cluster ==")
    show("first-of-cluster", [s for s in ms2 if s["first"]])
    show("continuation", [s for s in ms2 if not s["first"]])
    #.dir split for dpos (fade at day-high = PUT? check)
    print("== W3 x direction ==")
    show("PUT @day-high", [s for s in ms2 if s["dir"] == "PUT" and s["dpos"] == "high"])
    show("PUT @mid", [s for s in ms2 if s["dir"] == "PUT" and s["dpos"] == "mid"])
    show("CALL @day-low", [s for s in ms2 if s["dir"] == "CALL" and s["dpos"] == "low"])
    show("CALL @mid", [s for s in ms2 if s["dir"] == "CALL" and s["dpos"] == "mid"])


if __name__ == "__main__":
    main()

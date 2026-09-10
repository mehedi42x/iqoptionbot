#!/usr/bin/env python3
"""Comb operation P3: C1/C2/C3 cuts + flips + swaps + C4-hunt + L1-singles.
Bars: dW>0 & dL<0 & WR-up & TR-up & HO-up; cuts need TR<0 & HO<0 & >=2/3 blocks neg."""
import sys
sys.path.insert(0, ".")
from lab_comb_mtf import regen, net, show_slice, HO_START, P, B1_END, B2_END
from lab_comb_mtf2 import e1b_raw
from datetime import datetime, timezone

BASE = None


def busy_keep(raw):
    raw = sorted(raw, key=lambda x: x["t"])
    busy, kept = None, []
    for x in raw:
        if busy is not None and x["t"] < busy:
            continue
        busy = x["t"] + 60
        kept.append(x)
    return kept


def show2(name, kept, pool=None):
    W, L, D, nn = net(kept)
    wr = 100 * W / (W + L)
    nt = net([x for x in kept if x["t"] < HO_START])[3]
    nh = net([x for x in kept if x["t"] >= HO_START])[3]
    nb = [net([x for x in kept if x["t"] < B1_END])[3],
          net([x for x in kept if B1_END <= x["t"] < B2_END])[3],
          net([x for x in kept if x["t"] >= B2_END])[3]]
    dW, dL = W - BASE["W"], L - BASE["L"]
    dwr = wr - BASE["wr"]
    ok = (dW > 0 and dL < 0 and dwr > 0 and nt > BASE["TR"] and nh > BASE["HO"])
    pl = f" pool={pool}" if pool is not None else ""
    print(f"{'PASS' if ok else '    '} {name:24s} | n={len(kept):5d} {wr:5.2f}% {nn:+8.1f} | "
          f"TR {nt:+8.1f} HO {nh:+8.1f} | B {nb[0]:+7.1f} {nb[1]:+7.1f} {nb[2]:+7.1f} | "
          f"dW={dW:+d} dL={dL:+d} dWR={dwr:+.2f}{pl}")


def main():
    global BASE
    kept, raw = regen()
    W, L, D, nn = net(kept)
    BASE = {"n": len(kept), "W": W, "L": L, "wr": 100 * W / (W + L),
            "TR": net([x for x in kept if x["t"] < HO_START])[3],
            "HO": net([x for x in kept if x["t"] >= HO_START])[3]}
    print(f"BASE: n={len(kept)} WR={BASE['wr']:.2f}% net={nn:+.1f} TR={BASE['TR']:+.1f} HO={BASE['HO']:+.1f}")

    c1e = [x for x in kept if x["leg"] == "FADE" and x["eh"] == 6 and x["tmode"] == "with"]
    c1s = [x for x in kept if x["leg"] == "FADE" and x["sh"] == 6 and x["tmode"] == "with"]
    c2e = [x for x in kept if x["leg"] == "FADE" and x["eh"] == 6 and (x["size"] or 0) >= 1.5]
    t1, t2 = {x["t"] for x in c1e}, {x["t"] for x in c2e}
    print(f"C1e n={len(c1e)} C1s n={len(c1s)} C2e n={len(c2e)} overlap={len(t1 & t2)} union={len(t1 | t2)}")

    def cut(name, pred):
        f = [x for x in raw if not pred(x)]
        show2(name, busy_keep(f), len(raw) - len(f))
        return f

    print("\n### Cuts")
    cut("C1e h06-FADE-with(eh)", lambda x: x["leg"] == "FADE" and x["eh"] == 6 and x["tmode"] == "with")
    cut("C1s h06-FADE-with(sh)", lambda x: x["leg"] == "FADE" and x["sh"] == 6 and x["tmode"] == "with")
    cut("C2e h06-FADE-big(eh)", lambda x: x["leg"] == "FADE" and x["eh"] == 6 and (x["size"] or 0) >= 1.5)
    cut("C12e C1e+C2e", lambda x: (x["leg"] == "FADE" and x["eh"] == 6
                                  and (x["tmode"] == "with" or (x["size"] or 0) >= 1.5)))
    cut("C3 CM-CALL-vs", lambda x: x["leg"] == "FADE_CALM_MID" and x["dir"] == "CALL" and x["tmode"] == "vs")

    print("\n### Flips (WIN<->LOSS, same ts => same busy)")
    def flip(name, pred):
        f = []
        for x in raw:
            if pred(x):
                y = dict(x)
                y["r"] = {"WIN": "LOSS", "LOSS": "WIN"}.get(x["r"], x["r"])
                f.append(y)
            else:
                f.append(x)
        show2(name, busy_keep(f))
    flip("F1 flip-C1e", lambda x: x["leg"] == "FADE" and x["eh"] == 6 and x["tmode"] == "with")
    flip("F2 flip-C2e", lambda x: x["leg"] == "FADE" and x["eh"] == 6 and (x["size"] or 0) >= 1.5)
    flip("F12 flip-C1e+C2e", lambda x: (x["leg"] == "FADE" and x["eh"] == 6
                                        and (x["tmode"] == "with" or (x["size"] or 0) >= 1.5)))

    print("\n### Swaps")
    l1 = e1b_raw({20, 23})
    c1r = lambda x: x["leg"] == "FADE" and x["eh"] == 6 and x["tmode"] == "with"
    c3r = lambda x: x["leg"] == "FADE_CALM_MID" and x["dir"] == "CALL" and x["tmode"] == "vs"
    c12r = lambda x: (x["leg"] == "FADE" and x["eh"] == 6
                      and (x["tmode"] == "with" or (x["size"] or 0) >= 1.5))
    show2("S1 L1+C1e+C3", busy_keep([x for x in raw if not (c1r(x) or c3r(x))] + l1))
    show2("S2 L1+C12e+C3", busy_keep([x for x in raw if not (c12r(x) or c3r(x))] + l1))

    print("\n### L1 singles")
    show2("L1a E1B@h20", busy_keep(raw + e1b_raw({20})))
    show2("L1b E1B@h23", busy_keep(raw + e1b_raw({23})))

    print("\n### C4 hunt")
    fw = [x for x in kept if x["leg"] == "FADE" and x["tmode"] == "with"]
    show_slice("C4 FADE-with x eh", fw, lambda x: f"h{x['eh']:02d}", 30)
    cm = [x for x in kept if x["leg"] == "FADE_CALM_MID"]
    show_slice("C4 CM x dir x tmode", cm, lambda x: f"{x['dir']}:{x['tmode']}", 15)


if __name__ == "__main__":
    main()

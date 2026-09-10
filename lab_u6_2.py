#!/usr/bin/env python3
"""U6 round 2: golden-hour adds, Asia-E1B, big-pos E1B, unconfirmed-cuts, A2+A3 union.
Bars: profit-up ranked, WR>=60.43%, TR-up, HO-up, blocks all-up."""
import sys
sys.path.insert(0, ".")
from lab_u6_1 import regen_u5, busy_keep
from lab_comb_mtf import net, HO_START, B1_END, B2_END, hmorph
from lab_mtf import (C30, M1, MF, M1X, S30X, ctx1m, res30, res1m, SKIP)
from lab_mtf2 import feats30
from lab_comb_mtf2 import MS2SIG
from datetime import datetime, timezone

BASE = None


def show2(name, kept, pool=None):
    W, L, D, nn = net(kept)
    wr = 100 * W / (W + L)
    nt = net([x for x in kept if x["t"] < HO_START])[3]
    nh = net([x for x in kept if x["t"] >= HO_START])[3]
    nb = [net([x for x in kept if x["t"] < B1_END])[3],
          net([x for x in kept if B1_END <= x["t"] < B2_END])[3],
          net([x for x in kept if x["t"] >= B2_END])[3]]
    dW, dL = W - BASE["W"], L - BASE["L"]
    ok = (nn > BASE["net"] and wr >= BASE["wr"] and nt > BASE["TR"] and nh > BASE["HO"]
          and nb[0] > BASE["B"][0] and nb[1] > BASE["B"][1] and nb[2] > BASE["B"][2])
    pl = f" pool={pool}" if pool is not None else ""
    print(f"{'PASS' if ok else '    '} {name:24s} | n={len(kept):5d} {wr:5.2f}% {nn:+8.1f} | "
          f"TR {nt:+8.1f} HO {nh:+8.1f} | B {nb[0]:+7.1f} {nb[1]:+7.1f} {nb[2]:+7.1f} | "
          f"dW={dW:+d} dL={dL:+d}{pl}")


def e1b_gen(hours, pos_lo=0.80, size_lo=0.0, size_hi=1.0, vsT=False):
    out = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in MS2SIG:
            continue
        if datetime.fromtimestamp(t, tz=timezone.utc).hour not in hours:
            continue
        f = feats30(i)
        if f is None or f["pos"] < pos_lo:
            continue
        j = ctx1m(t)
        if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
            continue
        s = f["rg"] / MF[j]["atr"]
        if not (size_lo <= s < size_hi):
            continue
        if vsT:
            tr = MF[j]["trend"]
            if not ((tr == 1 and f["dir"] == "PUT") or (tr == -1 and f["dir"] == "CALL")):
                continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        out.append({"t": t, "r": r})
    return out


def m1_add(pred):
    out = []
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        if t in MS2SIG:
            continue
        f = MF[j - 1]
        if f["flat"] or f["doji"]:
            continue
        dd = "PUT" if f["bull"] else "CALL"
        if not pred(f, dd):
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        out.append({"t": t, "r": r})
    return out


def main():
    global BASE
    kept, raw = regen_u5()
    W, L, D, nn = net(kept)
    BASE = {"n": len(kept), "W": W, "L": L, "wr": 100 * W / (W + L), "net": nn,
            "TR": net([x for x in kept if x["t"] < HO_START])[3],
            "HO": net([x for x in kept if x["t"] >= HO_START])[3],
            "B": [net([x for x in kept if x["t"] < B1_END])[3],
                  net([x for x in kept if B1_END <= x["t"] < B2_END])[3],
                  net([x for x in kept if x["t"] >= B2_END])[3]]}
    print(f"BASE U5: n={len(kept)} WR={BASE['wr']:.2f}% net={nn:+.1f} TR={BASE['TR']:+.1f} HO={BASE['HO']:+.1f} "
          f"B={BASE['B'][0]:+.1f}/{BASE['B'][1]:+.1f}/{BASE['B'][2]:+.1f}")

    show2("B1 SKIP-nrm.75", busy_keep(raw + m1_add(
        lambda f, dd: f["hour"] in SKIP and not f["calm"] and 0.75 <= f["pos"] < 0.80)))
    show2("B2 monst-nrm.85", busy_keep(raw + m1_add(
        lambda f, dd: f["hour"] in (19, 23) and not f["calm"] and 0.85 <= f["pos"] < 0.90)))
    show2("B3 E1B@h012", busy_keep(raw + e1b_gen({0, 1, 2})))
    show2("B4 E1B@h34", busy_keep(raw + e1b_gen({3, 4})))
    show2("B5 E1B@h23 p.85", busy_keep(raw + e1b_gen({23}, pos_lo=0.85)))
    show2("B6 E1B-big+p.85", busy_keep(raw + e1b_gen({20, 21, 22, 23}, pos_lo=0.85, size_lo=1.0, size_hi=2.0)))

    def fresh_agrees(t, side):
        i = S30X.get(t - 30)
        if i is None:
            return None
        k = C30[i]
        m = hmorph(k["open"], k["high"], k["low"], k["close"])
        if m is None:
            return False
        return m["dir"] == side and m["pos"] >= 0.80

    b7 = [x for x in raw if not (x["leg"] == "FADE" and fresh_agrees(x["t"], x["dir"]) is False)]
    show2("B7 FADE-unconf-cut", busy_keep(b7), len(raw) - len(b7))
    b8 = [x for x in raw if not (x["leg"] in ("FADE_SKIP", "FADE_SKIP_CALM") and fresh_agrees(x["t"], x["dir"]) is False)]
    show2("B8 SKIP-unconf-cut", busy_keep(b8), len(raw) - len(b8))

    a2 = e1b_gen({23}, vsT=True)
    a3 = e1b_gen({23}, size_hi=0.75)
    show2("B9 A2+A3-union", busy_keep(raw + a2 + a3), f"{len(a2)}+{len(a3)}")

    # B10: E1B-h19 marginal probe (diagnostic)
    h19 = e1b_gen({19})
    k19 = busy_keep(raw + h19)
    new = [x for x in k19 if x["t"] in {y["t"] for y in h19}]
    print(f"B10 E1B-h19-marginal kept-sample: n={len(new)} "
          f"(WR/net need features; totals via A1: dW+105/dL+107, dilutive)")


if __name__ == "__main__":
    main()

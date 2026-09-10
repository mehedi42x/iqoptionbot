#!/usr/bin/env python3
"""U6 round 1: U5 forensics + new legs/filters/time-rules. Goal: PROFIT max, WR>=U5.
Bars: profit-up (rank), WR>=60.43%, TR-up, HO-up, blocks all-up."""
import sys
sys.path.insert(0, ".")
from lab_comb_mtf import net, show_slice, HO_START, P, B1_END, B2_END, V1_HI
from lab_mtf import (C30, M1, MF, M1X, S30X, ctx1m, res30, res1m, ms2_1m,
                     SKIP, WEAK)
from lab_mtf2 import feats30
from lab_comb_mtf import ms2_mod, hmorph, runup_1m, runup_30, VOL1M, VOL30
from lab_comb_mtf2 import e1b_raw, MS2SIG
from datetime import datetime, timezone
from collections import defaultdict
import math


def dt(t):
    return datetime.fromtimestamp(t, tz=timezone.utc)


def regen_u5():
    """U5 = U4 + E1B@h20 + H06-FADE veto. Returns (kept, raw)."""
    raw = []
    for j in range(1, len(M1)):
        d = ms2_1m(j - 1)
        if d is None:
            continue
        t = M1[j]["ts"]
        s, f = M1[j - 1], MF[j - 1]
        m = hmorph(s["open"], s["high"], s["low"], s["close"])
        tr = f["trend"]
        tmode = "flat" if tr == 0 else ("vs" if (tr == 1 and d == "PUT") or (tr == -1 and d == "CALL") else "with")
        leg = ms2_mod(j - 1)
        size = (m["rng"] / f["atr"] if f["atr"] else None)
        if leg == "FADE" and dt(t).hour == 6 and (tmode == "with" or (size or 0) >= 1.5):
            continue  # H06 veto (mirrors strategy incl. trend-None=>with quirk)
        r = res1m(j, d)
        if r is None:
            continue
        raw.append({"t": t, "r": r, "leg": leg, "tf": 60, "dir": d,
                    "eh": dt(t).hour, "wd": dt(t).strftime("%a"), "sh": f["hour"],
                    "pos": m["pos"], "bull": m["bull"], "body": m["body"],
                    "rng": m["rng"], "calm": f["calm"], "tmode": tmode,
                    "atr": f["atr"], "size": size,
                    "vol": VOL1M.get(s["ts"]), "ctxpos": None})
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in MS2SIG:
            continue
        if dt(t).hour not in (20, 21, 22):
            continue
        f = feats30(i)
        if f is None or f["pos"] < 0.80:
            continue
        j = ctx1m(t)
        if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
            continue
        if f["rg"] / MF[j]["atr"] >= 1.0:
            continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        k = C30[i - 1]
        m = hmorph(k["open"], k["high"], k["low"], k["close"])
        g = MF[j]
        tr = g["trend"]
        raw.append({"t": t, "r": r, "leg": "E1B_30S", "tf": 30, "dir": f["dir"],
                    "eh": dt(t).hour, "wd": dt(t).strftime("%a"), "sh": dt(k["ts"]).hour,
                    "pos": m["pos"], "bull": m["bull"], "body": m["body"],
                    "rng": m["rng"], "calm": g["calm"],
                    "tmode": "flat" if tr == 0 else ("vs" if (tr == 1 and f["dir"] == "PUT") or (tr == -1 and f["dir"] == "CALL") else "with"),
                    "atr": g["atr"], "size": f["rg"] / g["atr"],
                    "vol": VOL30.get(k["ts"]), "ctxpos": g["pos"]})
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        if t in MS2SIG:
            continue
        f = MF[j - 1]
        if f["flat"] or f["doji"]:
            continue
        if f["hour"] in WEAK or f["hour"] in SKIP:
            continue
        if not (0.85 <= f["pos"] < 0.93):
            continue
        dd = "PUT" if f["bull"] else "CALL"
        i2 = S30X.get(M1[j - 1]["ts"] + 30)
        if i2 is None:
            continue
        k = C30[i2]
        m2 = hmorph(k["open"], k["high"], k["low"], k["close"])
        if m2 is None or m2["pos"] < 0.90 or m2["dir"] != dd:
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        s = M1[j - 1]
        m = hmorph(s["open"], s["high"], s["low"], s["close"])
        tr = f["trend"]
        raw.append({"t": t, "r": r, "leg": "G1M_FRESH30", "tf": 60, "dir": dd,
                    "eh": dt(t).hour, "wd": dt(t).strftime("%a"), "sh": f["hour"],
                    "pos": m["pos"], "bull": m["bull"], "body": m["body"],
                    "rng": m["rng"], "calm": f["calm"],
                    "tmode": "flat" if tr == 0 else ("vs" if (tr == 1 and dd == "PUT") or (tr == -1 and dd == "CALL") else "with"),
                    "atr": f["atr"], "size": (m["rng"] / f["atr"] if f["atr"] else None),
                    "vol": VOL1M.get(s["ts"]), "ctxpos": None})
    raw.sort(key=lambda x: x["t"])
    busy, kept = None, []
    for x in raw:
        if busy is not None and x["t"] < busy:
            continue
        busy = x["t"] + 60
        kept.append(x)
    return kept, raw


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
    ok = (nn > BASE["net"] and wr >= BASE["wr"] and nt > BASE["TR"] and nh > BASE["HO"]
          and nb[0] > BASE["B"][0] and nb[1] > BASE["B"][1] and nb[2] > BASE["B"][2])
    pl = f" pool={pool}" if pool is not None else ""
    print(f"{'PASS' if ok else '    '} {name:24s} | n={len(kept):5d} {wr:5.2f}% {nn:+8.1f} | "
          f"TR {nt:+8.1f} HO {nh:+8.1f} | B {nb[0]:+7.1f} {nb[1]:+7.1f} {nb[2]:+7.1f} | "
          f"dW={dW:+d} dL={dL:+d}{pl}")


def main():
    global BASE
    kept, raw = regen_u5()
    W, L, D, nn = net(kept)
    print(f"U5 regen: n={len(kept)} W={W} L={L} D={D} WR={100*W/(W+L):.2f}% net={nn:+.1f} "
          f"(backtest told 6293/3599/2357/337/60.43%/702.2)")
    import csv
    bt = list(csv.DictReader(open("backtest_mtfv2__trades_60s.csv")))
    a = sorted(x["t"] for x in kept)
    b = sorted(float(r["entry_time"]) for r in bt)
    print("ENTRY-MATCH:", "EXACT" if a == b else "DIFF!")
    if a != b:
        return
    BASE = {"n": len(kept), "W": W, "L": L, "wr": 100 * W / (W + L), "net": nn,
            "TR": net([x for x in kept if x["t"] < HO_START])[3],
            "HO": net([x for x in kept if x["t"] >= HO_START])[3],
            "B": [net([x for x in kept if x["t"] < B1_END])[3],
                  net([x for x in kept if B1_END <= x["t"] < B2_END])[3],
                  net([x for x in kept if x["t"] >= B2_END])[3]]}

    print("\n### U5 forensics (fresh)")
    show_slice("F1 hour", kept, lambda x: f"h{x['eh']:02d}", 40)
    show_slice("F2 SKIP x hour", [x for x in kept if x["leg"] == "FADE_SKIP"],
               lambda x: f"h{x['eh']:02d}", 30)
    show_slice("F3 FADE x hour", [x for x in kept if x["leg"] == "FADE"],
               lambda x: f"h{x['eh']:02d}", 30)
    show_slice("F4 FADE-with x hour", [x for x in kept if x["leg"] == "FADE" and x["tmode"] == "with"],
               lambda x: f"h{x['eh']:02d}", 20)
    show_slice("F5 E1B-h20 cells", [x for x in kept if x["leg"] == "E1B_30S" and x["eh"] == 20],
               lambda x: x["tmode"], 20)
    show_slice("F6 E1B x hour", [x for x in kept if x["leg"] == "E1B_30S"],
               lambda x: f"h{x['eh']:02d}", 30)
    show_slice("F7 weekday", kept, lambda x: x["wd"], 40)
    show_slice("F8 tmode x leg", kept, lambda x: f"{x['leg']}:{x['tmode']}", 40)
    show_slice("F9 pos ALL", kept, lambda x: (
        "p<.85" if x["pos"] < 0.85 else ("p.85-.90" if x["pos"] < 0.90 else (
            "p.90-.93" if x["pos"] < 0.93 else ("p.93-.95" if x["pos"] < 0.95 else "p.95+")))), 50)
    show_slice("F10 size ALL", kept, lambda x: (
        "s<.75" if (x["size"] or 9) < 0.75 else ("s.75-1" if (x["size"] or 9) < 1.0 else (
            "s1-1.5" if (x["size"] or 9) < 1.5 else ("s1.5-2" if (x["size"] or 9) < 2.0 else "s2+")))), 50)

    print("\n### Candidates")
    show2("A1 E1B@h19", busy_keep(raw + e1b_raw({19})))
    # A2: E1B@h23 + vsT
    a2 = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in MS2SIG or dt(t).hour != 23:
            continue
        f = feats30(i)
        if f is None or f["pos"] < 0.80:
            continue
        j = ctx1m(t)
        if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
            continue
        if f["rg"] / MF[j]["atr"] >= 1.0:
            continue
        tr = MF[j]["trend"]
        if not ((tr == 1 and f["dir"] == "PUT") or (tr == -1 and f["dir"] == "CALL")):
            continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        a2.append({"t": t, "r": r})
    show2("A2 E1B@h23+vsT", busy_keep(raw + a2), len(a2))
    show2("A3 E1B@h23 sz<.75", busy_keep(raw + e1b_raw({23}, size_hi=0.75)))
    # A4: h04 normal >=0.90 ; A5: monster >=0.88 ; A7: calm-mid .83-.85
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
    show2("A4 h04-nrm.90+", busy_keep(raw + m1_add(
        lambda f, dd: f["hour"] == 4 and 0.90 <= f["pos"] < 0.93)))
    show2("A5 monst.88+", busy_keep(raw + m1_add(
        lambda f, dd: f["hour"] in (19, 23) and 0.88 <= f["pos"] < 0.90)))
    show2("A7 cm-mid.83+", busy_keep(raw + m1_add(
        lambda f, dd: f["hour"] not in SKIP and f["calm"] and 0.83 <= f["pos"] < 0.85)))
    # A8: 30s follow >=.93 (dead-check)
    a8 = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in MS2SIG or dt(t).hour in WEAK:
            continue
        k = C30[i - 1]
        rg = k["high"] - k["low"]
        if rg <= 0 or k["close"] == k["open"]:
            continue
        b = k["close"] > k["open"]
        p = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
        if p < 0.93:
            continue
        r = res30(i, "CALL" if b else "PUT")
        if r is None:
            continue
        a8.append({"t": t, "r": r})
    show2("A8 30s-follow.93", busy_keep(raw + a8), len(a8))
    # A9: 1m BB20/2 fade (marginal)
    cl = [r["close"] for r in M1]
    a9 = []
    for j in range(20, len(M1)):
        t = M1[j]["ts"]
        if t in MS2SIG:
            continue
        w = cl[j - 20:j]
        mu = sum(w) / 20
        sd = math.sqrt(sum((c - mu) ** 2 for c in w) / 20)
        if sd <= 0:
            continue
        c = cl[j - 1]
        dd = None
        if c > mu + 2 * sd:
            dd = "PUT"
        elif c < mu - 2 * sd:
            dd = "CALL"
        if dd is None:
            continue
        h = dt(M1[j - 1]["ts"]).hour
        if h in WEAK:
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        a9.append({"t": t, "r": r})
    show2("A9 BB20-fade", busy_keep(raw + a9), len(a9))
    show2("A10 E1B21/22 sz1+", busy_keep(raw + e1b_raw({21, 22}, size_lo=1.0, size_hi=1.25)))
    show2("A12 E1B@h20 sz1+", busy_keep(raw + e1b_raw({20}, size_lo=1.0, size_hi=1.5)))
    # A13: E1B@h20 pos .75-.80
    a13 = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in MS2SIG or dt(t).hour != 20:
            continue
        f = feats30(i)
        if f is None or not (0.75 <= f["pos"] < 0.80):
            continue
        j = ctx1m(t)
        if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
            continue
        if f["rg"] / MF[j]["atr"] >= 1.0:
            continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        a13.append({"t": t, "r": r})
    show2("A13 E1B@h20 p.75", busy_keep(raw + a13), len(a13))
    # C1: soft-hour chop veto (FADE + eh in 0/7/16/17 + with/big)
    c1 = [x for x in raw if not (x["leg"] == "FADE" and x["eh"] in (0, 7, 16, 17)
                                and (x["tmode"] == "with" or (x["size"] or 0) >= 1.5))]
    show2("C1 soft-chop-veto", busy_keep(c1), len(raw) - len(c1))


if __name__ == "__main__":
    main()

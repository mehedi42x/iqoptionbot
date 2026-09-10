#!/usr/bin/env python3
"""Comb operation P2: fine-cell probes + adds + vetoes on U4.
Bars (user): dW>0 & dL<0 & WR-up & TR-up & HO-up. Swaps/flips only can pass."""
import sys
sys.path.insert(0, ".")
from lab_comb_mtf import regen, net, show_slice, HO_START, P, B1_END, B2_END, V1_HI
from lab_mtf import (C30, M1, MF, M1X, S30X, ctx1m, res30, res1m, ms2_1m,
                     SKIP, WEAK)
from lab_mtf2 import feats30
from datetime import datetime, timezone


def busy_keep(raw):
    raw = sorted(raw, key=lambda x: x["t"])
    busy, kept = None, []
    for x in raw:
        if busy is not None and x["t"] < busy:
            continue
        busy = x["t"] + 60
        kept.append(x)
    return kept


BASE = None


def show2(name, kept, pool=None):
    W, L, D, nn = net(kept)
    wr = 100 * W / (W + L)
    tr = [x for x in kept if x["t"] < HO_START]
    ho = [x for x in kept if x["t"] >= HO_START]
    b1 = [x for x in kept if x["t"] < B1_END]
    b2 = [x for x in kept if B1_END <= x["t"] < B2_END]
    b3 = [x for x in kept if x["t"] >= B2_END]
    nt = net(tr)[3]
    nh = net(ho)[3]
    nb = [net(b)[3] for b in (b1, b2, b3)]
    B = BASE
    dW, dL, dn = W - B["W"], L - B["L"], len(kept) - B["n"]
    dwr = wr - B["wr"]
    ok = (dW > 0 and dL < 0 and dwr > 0 and nt > B["TR"] and nh > B["HO"])
    flag = "PASS" if ok else ("    ")
    pl = f" pool={pool}" if pool is not None else ""
    print(f"{flag} {name:26s} | n={len(kept):5d} {wr:5.2f}% {nn:+8.1f} | TR {nt:+8.1f} HO {nh:+8.1f} | "
          f"B {nb[0]:+7.1f} {nb[1]:+7.1f} {nb[2]:+7.1f} | dW={dW:+d} dL={dL:+d} dWR={dwr:+.2f}{pl}")


MS2SIG = set()
for _j in range(1, len(M1)):
    if ms2_1m(_j - 1) is not None:
        MS2SIG.add(M1[_j]["ts"])


def e1b_raw(hours, pos_lo=0.80, size_lo=0.0, size_hi=1.0):
    out = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in MS2SIG:  # strategy tie-suppress mirror (incl. Friday-edge ghosts)
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
        r = res30(i, f["dir"])
        if r is None:
            continue
        out.append({"t": t, "r": r})
    return out


def g1m_raw(pos_lo=0.85, pos_hi=0.93, fresh_lo=0.90):
    out = []
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        f = MF[j - 1]
        if f["flat"] or f["doji"]:
            continue
        if f["hour"] in WEAK or f["hour"] in SKIP:
            continue
        if not (pos_lo <= f["pos"] < pos_hi):
            continue
        dd = "PUT" if f["bull"] else "CALL"
        i2 = S30X.get(M1[j - 1]["ts"] + 30)
        if i2 is None:
            continue
        k = C30[i2]
        rg = k["high"] - k["low"]
        if rg <= 0 or k["close"] == k["open"]:
            continue
        b = k["close"] > k["open"]
        p2 = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
        if p2 < fresh_lo or ("PUT" if b else "CALL") != dd:
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        out.append({"t": t, "r": r})
    return out


def main():
    global BASE
    kept, raw = regen()
    W, L, D, nn = net(kept)
    trn = net([x for x in kept if x["t"] < HO_START])[3]
    hon = net([x for x in kept if x["t"] >= HO_START])[3]
    BASE = {"n": len(kept), "W": W, "L": L, "wr": 100 * W / (W + L), "TR": trn, "HO": hon,
            "raw": raw}
    print(f"BASE U4: n={len(kept)} W={W} L={L} D={D} WR={BASE['wr']:.2f}% net={nn:+.1f} TR={trn:+.1f} HO={hon:+.1f}")

    print("\n### Part 1: fine-cell probes (need TR<0 & HO<0, n>=50)")
    g1m = [x for x in kept if x["leg"] == "G1M_FRESH30"]
    show_slice("P-A G1M@h1215", g1m, lambda x: f"h1215{x['sh'] in (12,15)}", 10)
    h6f = [x for x in kept if x["eh"] == 6 and x["leg"] == "FADE"]
    show_slice("P-B h06-FADE x tmode", h6f, lambda x: x["tmode"], 20)
    show_slice("P-C h06-FADE x calm", h6f, lambda x: f"{'c' if x['calm'] else 'n'}", 20)
    show_slice("P-C2 h06-FADE x size", h6f, lambda x: f"s{'big' if (x['size'] or 0)>=1.5 else 'sml'}", 20)
    sklo = [x for x in kept if x["leg"] == "FADE_SKIP" and x["pos"] < 0.90]
    show_slice("P-D1 SKIP-lo x tmode", sklo, lambda x: x["tmode"], 20)
    show_slice("P-D2 SKIP-lo x calm", sklo, lambda x: f"{'c' if x['calm'] else 'n'}", 20)
    skmid = [x for x in kept if x["leg"] == "FADE_SKIP" and 0.93 <= x["pos"] < 0.95]
    show_slice("P-D3 SKIP-p93-95 x tmode", skmid, lambda x: x["tmode"], 10)
    fbig = [x for x in kept if x["leg"] == "FADE" and (x["size"] or 0) >= 1.5]
    show_slice("P-E1 FADE-big x tmode", fbig, lambda x: x["tmode"], 20)
    show_slice("P-E2 FADE-big x calm", fbig, lambda x: f"{'c' if x['calm'] else 'n'}", 20)
    emid = [x for x in kept if x["leg"] == "E1B_30S" and 0.5 <= x["size"] < 0.75]
    show_slice("P-F1 E1B-midsz x tmode", emid, lambda x: x["tmode"], 10)
    e1h = [x for x in kept if x["leg"] == "E1B_30S" and x["em"] < 30]
    show_slice("P-F2 E1B-1sthalf x tmode", e1h, lambda x: x["tmode"], 10)
    cmc = [x for x in kept if x["leg"] == "FADE_CALM_MID" and x["dir"] == "CALL"]
    show_slice("P-G1 CM-CALL x tmode", cmc, lambda x: x["tmode"], 10)
    cmw = [x for x in kept if x["leg"] == "FADE_CALM_MID" and x["tmode"] == "with"]
    show_slice("P-G2 CM-with x dir", cmw, lambda x: x["dir"], 10)
    show_slice("P-H vhi x tmode", [x for x in kept if x["tf"] == 60 and (x["vol"] or 0) >= V1_HI],
               lambda x: x["tmode"], 20)
    h16 = [x for x in kept if x["eh"] == 16]
    show_slice("P-J1 h16 x leg", h16, lambda x: x["leg"], 15)
    h17 = [x for x in kept if x["eh"] == 17]
    show_slice("P-J2 h17 x leg", h17, lambda x: x["leg"], 15)
    show_slice("P-N2 hour-start mm<5", kept, lambda x: f"mm5{x['em'] < 5}", 50)

    print("\n### Part 2: adds (union through busy)")
    base_raw = BASE["raw"]
    a = e1b_raw({20, 23})
    show2("L1 E1B@h20/23", busy_keep(base_raw + a), len(a))
    lo = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if datetime.fromtimestamp(t, tz=timezone.utc).hour not in (21, 22):
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
        lo.append({"t": t, "r": r})
    show2("L2 E1B pos.75-.80", busy_keep(base_raw + lo), len(lo))
    a = e1b_raw({21, 22}, size_lo=1.0, size_hi=1.25)
    show2("L3 E1B size1-1.25", busy_keep(base_raw + a), len(a))
    a = g1m_raw(fresh_lo=0.85)
    show2("L4 G1M fresh.85+", busy_keep(base_raw + a), len(a))
    a = g1m_raw(pos_lo=0.80, pos_hi=0.85)
    show2("L5 G1M 1m.80-.85", busy_keep(base_raw + a), len(a))
    # L10: 1m .90-.93 + fresh>=.93, non-weak non-skip excl h12/15
    l10 = []
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        f = MF[j - 1]
        if f["flat"] or f["doji"]:
            continue
        if f["hour"] in WEAK or f["hour"] in SKIP or f["hour"] in (12, 15):
            continue
        if not (0.90 <= f["pos"] < 0.93):
            continue
        dd = "PUT" if f["bull"] else "CALL"
        i2 = S30X.get(M1[j - 1]["ts"] + 30)
        if i2 is None:
            continue
        k = C30[i2]
        rg = k["high"] - k["low"]
        if rg <= 0 or k["close"] == k["open"]:
            continue
        b = k["close"] > k["open"]
        p2 = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
        if p2 < 0.93 or ("PUT" if b else "CALL") != dd:
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        l10.append({"t": t, "r": r})
    show2("L10 1m.90-93+fr.93", busy_keep(base_raw + l10), len(l10))

    print("\n### Part 3: vetoes / cuts")
    def opp30(ts, side, lo):
        i = S30X.get(ts)
        if i is None:
            return False
        k = C30[i]
        rg = k["high"] - k["low"]
        if rg <= 0 or k["close"] == k["open"]:
            return False
        b = k["close"] > k["open"]
        p = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
        return p >= lo and ("PUT" if b else "CALL") != side
    # M1: veto 1m-entries where 2nd-half 30s opposes>=.80
    f1 = [x for x in raw if not (x["tf"] == 60 and opp30(x["t"] - 30, x["dir"], 0.80))]
    show2("M1 veto-2ndhalf-opp", busy_keep(f1), len(raw) - len(f1))
    # M2: veto 1m-entries where 1st-half 30s opposes>=.80
    f2 = [x for x in raw if not (x["tf"] == 60 and opp30(x["t"] - 60, x["dir"], 0.80))]
    show2("M2 veto-1sthalf-opp", busy_keep(f2), len(raw) - len(f2))
    # M3: veto E1B where ctx-1m opposes>=.85
    def ctx_opp(x):
        j = ctx1m(x["t"])
        if j is None:
            return False
        g = MF[j]
        return (not g["flat"] and not g["doji"] and g["pos"] is not None
                and g["pos"] >= 0.85 and ("PUT" if g["bull"] else "CALL") != x["dir"])
    f3 = [x for x in raw if not (x["leg"] == "E1B_30S" and ctx_opp(x))]
    show2("M3 veto-E1B-ctxopp", busy_keep(f3), len(raw) - len(f3))
    # N2: cut hour-start entries mm<5
    f4 = [x for x in raw if not (datetime.fromtimestamp(x["t"], tz=timezone.utc).minute < 5)]
    show2("N2 cut-mm<5", busy_keep(f4), len(raw) - len(f4))


if __name__ == "__main__":
    main()

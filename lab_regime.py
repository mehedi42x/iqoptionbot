#!/usr/bin/env python3
"""Regime forensics: which strategy wins in which market type?
Regime features = causal, O(1)-implementable live (ring buffers).
Vol cutoffs = TRAIN percentiles, FROZEN, applied to HO (no peeking).
Warmup: signal candle index >= 61 (mirrors live buffer warmup)."""
import sys
sys.path.insert(0, ".")
from forensics_mfv2 import build_v2
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

PAYOUT = 0.85
WARM = 61


def compute_feats(rows):
    n = len(rows)
    cl = [r["close"] for r in rows]
    rg = [r["high"] - r["low"] for r in rows]
    vr = [None] * n          # vol_ratio range5/range60
    bull = [None] * n        # trend stack state: +1/-1/0
    for i in range(n):
        if i >= 60:
            r5 = sum(rg[i - 4:i + 1]) / 5
            r60 = sum(rg[i - 59:i + 1]) / 60
            vr[i] = r5 / r60 if r60 > 0 else 1.0
        if i >= 50:
            s50 = sum(cl[i - 49:i + 1]) / 50
            s20 = sum(cl[i - 19:i + 1]) / 20
            c = cl[i]
            if c > s50 and s20 > s50:
                bull[i] = 1
            elif c < s50 and s20 < s50:
                bull[i] = -1
            else:
                bull[i] = 0
    return vr, bull


def main():
    sigs, allc, rows = build_v2()
    vr, bull = compute_feats(rows)
    # donch20 per row (causal)
    n = len(rows)
    hh = [r["high"] for r in rows]
    ll = [r["low"] for r in rows]
    cl = [r["close"] for r in rows]
    don = [None] * n
    for i in range(20, n):
        hlo = max(hh[i - 19:i + 1]) - min(ll[i - 19:i + 1])
        don[i] = (cl[i] - min(ll[i - 19:i + 1])) / hlo if hlo > 0 else 0.5
    # TRAIN-only vol cutoffs
    tr_vr = sorted(v for e in allc for v in [vr[e["i"] - 1]] if v is not None and e["ts"] < HOLDOUT_START)
    c1 = tr_vr[int(len(tr_vr) * 0.33)]
    c2 = tr_vr[int(len(tr_vr) * 0.66)]
    print(f"vol cutoffs (TRAIN-frozen): calm<{c1:.3f} storm>{c2:.3f}")

    def reg(e):
        v = vr[e["i"] - 1]
        return "calm" if v < c1 else ("storm" if v > c2 else "normal")

    def trend(e):
        return bull[e["i"] - 1]

    # attach; enforce warmup
    vsigs = [s for s in sigs if (s["i"] - 1) >= WARM and vr[s["i"] - 1] is not None and bull[s["i"] - 1] is not None]
    vall = [e for e in allc if (e["i"] - 1) >= WARM and vr[e["i"] - 1] is not None and bull[e["i"] - 1] is not None]
    print(f"v3 signals after warmup: {len(vsigs)} (allc {len(vall)})")

    def show_pool(name, pool):
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            if not ss:
                continue
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            print(f"  {name:30s} {sp}: n={len(ss):5d} WR={100*w/nn if nn else 0:5.2f}% ${w*PAYOUT-l:+8.1f}")

    def res(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def show_add(name, cond):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for e in vall:
            if e["flat"] or e["doji"]:
                continue
            if not cond(e):
                continue
            d = "PUT" if e["bull"] else "CALL"
            r = res(e["i"], d)
            idx = 0 if r == "WIN" else (2 if r == "DRAW" else 1)
            bk["HO" if e["ts"] >= HOLDOUT_START else "TR"][idx] += 1
            m = datetime.fromtimestamp(e["ts"], tz=timezone.utc).strftime("%Y-%m")
            bk[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][idx] += 1
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = bk[k]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l)
        t, h = row["TR"], row["HO"]
        print(f"  {name:30s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} | J{row['J'][2]:+7.1f} A{row['A'][2]:+7.1f} S{row['S'][2]:+7.1f}")

    print("\n== A: v3 WR by vol regime ==")
    for R in ("calm", "normal", "storm"):
        show_pool(f"vol={R}", [s for s in vsigs if reg(s) == R])

    print("\n== B: trend alignment (fade WITH trend vs VS trend) ==")
    def al(s):
        t = trend(s)
        with_tr = (t == 1 and s["dir"] == "CALL") or (t == -1 and s["dir"] == "PUT")
        vs_tr = (t == 1 and s["dir"] == "PUT") or (t == -1 and s["dir"] == "CALL")
        return "with" if with_tr else ("vs" if vs_tr else "flat")
    for A in ("with", "vs", "flat"):
        show_pool(f"align={A}", [s for s in vsigs if al(s) == A])
    for A in ("with", "vs"):
        for R in ("calm", "normal", "storm"):
            show_pool(f"align={A} vol={R}", [s for s in vsigs if al(s) == A and reg(s) == R])

    print("\n== C: weak-hour strategies (rescue?) ==")
    show_add("C1 weak+with-trend fade.93", lambda e: e["weak"] and ((trend(e) == 1 and not e["bull"]) or (trend(e) == -1 and e["bull"])) and e["pos"] >= 0.93)
    show_add("C2 weak+flat fade.93", lambda e: e["weak"] and trend(e) == 0 and e["pos"] >= 0.93)
    show_add("C3 weak+calm fade.93", lambda e: e["weak"] and reg(e) == "calm" and e["pos"] >= 0.93)
    show_add("C4 weak+vs-trend fade.93", lambda e: e["weak"] and ((trend(e) == 1 and e["bull"]) or (trend(e) == -1 and not e["bull"])) and e["pos"] >= 0.93)

    print("\n== D: vol-adaptive bars ==")
    show_add("D1 calm .90-.93 add", lambda e: not e["weak"] and not e["skip"] and reg(e) == "calm" and 0.90 <= e["pos"] < 0.93)
    show_add("D2 calm .85-.90 add?", lambda e: not e["weak"] and not e["skip"] and reg(e) == "calm" and 0.85 <= e["pos"] < 0.90)
    show_pool("D3 storm+normal-hrs (all v3)", [s for s in vsigs if reg(s) == "storm" and not s["skip"]])
    show_pool("D4 storm+skip-hrs", [s for s in vsigs if reg(s) == "storm" and s["skip"]])

    print("\n== E: range-edge (flat trend + donch edge) ==")
    show_add("E1 flat+edge .90-.93", lambda e: not e["weak"] and not e["skip"] and trend(e) == 0 and (don[e["i"] - 1] is not None and (don[e["i"] - 1] < 0.15 or don[e["i"] - 1] > 0.85)) and 0.90 <= e["pos"] < 0.93)
    show_add("E2 with-trend .90-.93", lambda e: not e["weak"] and not e["skip"] and ((trend(e) == 1 and not e["bull"]) or (trend(e) == -1 and e["bull"])) and 0.90 <= e["pos"] < 0.93)
    show_add("E3 vs-trend .90-.93", lambda e: not e["weak"] and not e["skip"] and ((trend(e) == 1 and e["bull"]) or (trend(e) == -1 and not e["bull"])) and 0.90 <= e["pos"] < 0.93)

    print("\n== F: skip hours x vol ==")
    show_pool("F1 skip+calm", [s for s in vsigs if s["skip"] and reg(s) == "calm"])
    show_pool("F2 skip+normal", [s for s in vsigs if s["skip"] and reg(s) == "normal"])
    show_pool("F3 skip+storm", [s for s in vsigs if s["skip"] and reg(s) == "storm"])


if __name__ == "__main__":
    main()

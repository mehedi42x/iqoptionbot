#!/usr/bin/env python3
"""Regime Round 3 (final hunt): marginal adds, regime micro-bars, weekday, MTF.
Adopt bar for adds: TRAIN>0 & HO>0 & 3/3 & FULL WR>59.66 (accretive)."""
import sys
sys.path.insert(0, ".")
from lab_regime import compute_feats, WARM
from forensics_mfv2 import build_v2
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

PAYOUT = 0.85
BASE_WR = 59.66


def main():
    sigs, allc, rows = build_v2()
    vr, bull = compute_feats(rows)
    tr_vr = sorted(v for e in allc for v in [vr[e["i"] - 1]] if v is not None and e["ts"] < HOLDOUT_START)
    c1 = tr_vr[int(len(tr_vr) * 0.33)]
    c2 = tr_vr[int(len(tr_vr) * 0.66)]

    # 5m resample (causal; aligned to epoch grid)
    f5 = {}   # row_idx -> (trend5, pos5extreme_dir or None)
    buckets = {}
    for i, r in enumerate(rows):
        b = int(r["ts"]) // 300
        buckets.setdefault(b, []).append(i)
    keys = sorted(buckets.keys())
    closes5, bull5, pos5 = {}, {}, {}
    for bi, b in enumerate(keys):
        idxs = buckets[b]
        o = rows[idxs[0]]["open"]
        c = rows[idxs[-1]]["close"]
        h = max(rows[j]["high"] for j in idxs)
        l = min(rows[idxs[0] - 1]["low"] if idxs[0] > 0 else rows[idxs[0]]["low"] for j in [0]) if False else min(rows[j]["low"] for j in idxs)
        closes5[b] = c
        rng = h - l
        if rng > 0:
            pos5[b] = (c - l) / rng if c >= o else (h - c) / rng
            pos5[b] = (pos5[b], "PUT" if c > o else ("CALL" if c < o else None))
        else:
            pos5[b] = (0.5, None)
        if bi >= 50:
            prev = [closes5[keys[k]] for k in range(bi - 50, bi + 1)]
            s50 = sum(prev[-50:]) / 50
            s20 = sum(prev[-20:]) / 20
            if c > s50 and s20 > s50:
                bull5[b] = 1
            elif c < s50 and s20 < s50:
                bull5[b] = -1
            else:
                bull5[b] = 0
    # map each 1m row -> last CLOSED 5m bucket strictly before its timestamp
    def feat5(ts):
        b = int(ts) // 300 - 1
        while b not in bull5 and b > keys[0]:
            b -= 1
        if b not in bull5:
            return None, None
        return bull5[b], pos5[b]

    def reg(e):
        v = vr[e["i"] - 1]
        return "calm" if v < c1 else ("storm" if v > c2 else "normal")

    def trend(e):
        return bull[e["i"] - 1]

    vall = [e for e in allc if (e["i"] - 1) >= WARM and vr[e["i"] - 1] is not None and bull[e["i"] - 1] is not None]
    vsigs = [s for s in sigs if (s["i"] - 1) >= WARM]

    def res(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def show(name, cond, follow=False):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for e in vall:
            if e["flat"] or e["doji"]:
                continue
            if not cond(e):
                continue
            d = ("CALL" if e["bull"] else "PUT") if follow else ("PUT" if e["bull"] else "CALL")
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
        fw = (t[0] * t[1] + h[0] * h[1]) / (t[0] + h[0]) if (t[0] + h[0]) else 0
        ok = "✅" if (t[2] > 0 and h[2] > 0 and row["J"][2] > 0 and row["A"][2] > 0 and row["S"][2] > 0 and fw > BASE_WR) else ("~ " if (t[2] > 0 and h[2] > 0) else "  ")
        print(f"{ok} {name:34s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} | J{row['J'][2]:+7.1f} A{row['A'][2]:+7.1f} S{row['S'][2]:+7.1f} | ~{fw:.2f}%")

    NW = lambda e: not e["weak"] and not e["skip"]
    print("== M: marginals & micro-bars ==")
    show("M1 vsT+run2 .90-.93 MARGINAL", lambda e: NW(e) and ((trend(e) == 1 and e["bull"]) or (trend(e) == -1 and not e["bull"])) and e["run"] >= 2 and 0.90 <= e["pos"] < 0.93)
    show("M2 skip20-22+calm .75-.80", lambda e: e["hour"] in (20, 21, 22) and reg(e) == "calm" and 0.75 <= e["pos"] < 0.80)
    show("M5 monst19/23+calm .85-.90", lambda e: NW(e) and e["hour"] in (19, 23) and reg(e) == "calm" and 0.85 <= e["pos"] < 0.90)
    print("== M3: micro-cut slice ==")
    show("M3 withT normal .93-.94", lambda e: NW(e) and ((trend(e) == 1 and not e["bull"]) or (trend(e) == -1 and e["bull"])) and 0.93 <= e["pos"] < 0.94)
    print("== X: MTF ==")
    show("X1 5mTrend+1m follow .85+", lambda e: NW(e) and (lambda t: t[0] is not None and t[0] != 0)(feat5(rows[e["i"] - 1]["ts"])) and e["pos"] >= 0.85, follow=True)
    show("X2 5mFlat+1m fade .90-.93", lambda e: NW(e) and (lambda t: t[0] == 0)(feat5(rows[e["i"] - 1]["ts"])) and 0.90 <= e["pos"] < 0.93)
    def x3cond(e):
        if not NW(e) or not (e["pos"] >= 0.90):
            return False
        t5, p5 = feat5(rows[e["i"] - 1]["ts"])
        if p5 is None or p5[1] is None or p5[0] < 0.90:
            return False
        fade1m = "PUT" if e["bull"] else "CALL"
        return fade1m == p5[1]
    show("X3 5m+1m confluence fade", x3cond)

    print("\n== M4: weekday forensics (v3 pool) ==")
    for wd in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
        for sp in ("TR", "HO"):
            ss = [s for s in vsigs if s["split"] == sp and datetime.fromtimestamp(rows[s["i"] - 1]["ts"], tz=timezone.utc).strftime("%a") == wd]
            if not ss:
                continue
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            print(f"  {wd} {sp}: n={len(ss):4d} WR={100*w/nn if nn else 0:5.2f}% ${w*PAYOUT-l:+7.1f}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Regime Round 2: does TREND-FOLLOWING win in trend regimes? (+ squeeze-breakout, flat-fade)
FOLLOW = direction WITH candle color. Judge: TRAIN>0 & HO>0 & 3/3 & accretion vs 59.66%."""
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

    def reg(e):
        v = vr[e["i"] - 1]
        return "calm" if v < c1 else ("storm" if v > c2 else "normal")

    def trend(e):
        return bull[e["i"] - 1]

    vall = [e for e in allc if (e["i"] - 1) >= WARM and vr[e["i"] - 1] is not None and bull[e["i"] - 1] is not None]

    def res(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def show(name, cond, follow):
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
        ok = "✅" if (t[2] > 0 and h[2] > 0 and row["J"][2] > 0 and row["A"][2] > 0 and row["S"][2] > 0) else "  "
        acc = "ACCR" if fw > BASE_WR else ("dil " if ok.strip() else "    ")
        print(f"{ok}{acc} {name:32s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} | J{row['J'][2]:+7.1f} A{row['A'][2]:+7.1f} S{row['S'][2]:+7.1f} | ~{fw:.2f}%")

    T = lambda e: trend(e) != 0
    NW = lambda e: not e["weak"] and not e["skip"]
    print("== follow legs (dir WITH candle) ==")
    show("T1 trend+follow .85+", lambda e: NW(e) and T(e) and e["pos"] >= 0.85, True)
    show("T1b trend+run2+follow .85+", lambda e: NW(e) and T(e) and e["run"] >= 2 and e["pos"] >= 0.85, True)
    show("T2 trend+follow .70-.85", lambda e: NW(e) and T(e) and 0.70 <= e["pos"] < 0.85, True)
    show("T3 trend+storm+follow .85+", lambda e: NW(e) and T(e) and reg(e) == "storm" and e["pos"] >= 0.85, True)
    show("T4 trend+calm+follow .80+", lambda e: NW(e) and T(e) and reg(e) == "calm" and e["pos"] >= 0.80, True)
    show("T5 weak+follow .85+", lambda e: e["weak"] and e["pos"] >= 0.85, True)
    show("T9 squeeze-break follow", lambda e: NW(e) and reg(e) == "calm" and e["body_atr"] >= 1.5 and e["pos"] >= 0.70, True)
    print("== fade legs ==")
    show("T6 flat+fade .90-.93", lambda e: NW(e) and trend(e) == 0 and 0.90 <= e["pos"] < 0.93, False)
    show("T10 vs-trend+run2+fade .90+", lambda e: NW(e) and ((trend(e) == 1 and e["bull"]) or (trend(e) == -1 and not e["bull"])) and e["run"] >= 2 and e["pos"] >= 0.90, False)


if __name__ == "__main__":
    main()

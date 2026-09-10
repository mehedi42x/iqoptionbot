#!/usr/bin/env python3
"""Round 5: final accretive-add hunt (7 pre-registered confluence tests).
Adopt only: TRAIN>0 & HO>0 & 3/3 months & FULL WR > 59.62% (accretive)."""
import sys
sys.path.insert(0, ".")
from forensics_mfv2 import build_v2
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

PAYOUT = 0.85
BASE_WR = 59.62


def main():
    sigs, allc, rows = build_v2()

    def res(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def show(name, cond):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for e in allc:
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
        fw = (t[0] * t[1] + h[0] * h[1]) / (t[0] + h[0]) if (t[0] + h[0]) else 0
        ok = "✅" if (t[2] > 0 and h[2] > 0 and row["J"][2] > 0 and row["A"][2] > 0 and row["S"][2] > 0 and fw > BASE_WR) else "  "
        print(f"{ok}{name:30s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} | J{row['J'][2]:+7.1f} A{row['A'][2]:+7.1f} S{row['S'][2]:+7.1f} | FULLwr~{fw:.2f}%")

    base = lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93
    print("== R5 confluence adds ==")
    show("G1 skip20-22 .70-.75", lambda e: e["hour"] in (20, 21, 22) and 0.70 <= e["pos"] < 0.75)
    show("G2 night2/4 .90-.93", lambda e: not e["weak"] and not e["skip"] and e["hour"] in (2, 4) and 0.90 <= e["pos"] < 0.93)
    show("G3 .85-.93 micro-body", lambda e: base(e) and e["body_atr"] < 0.3)
    show("G4 .85-.93 one-sided", lambda e: base(e) and ((e["bull"] and e["lo_wick"] < 0.05) or (e["bear"] and e["up_wick"] < 0.05)))
    show("G5 .85-.93 rsi-xtreme", lambda e: base(e) and ((e["bull"] and (e["rsi3"] or 50) > 80) or (e["bear"] and (e["rsi3"] or 50) < 20)))
    show("G6 .85-.93 fresh-rev", lambda e: base(e) and e["p1_same"] is False)
    show("G7 .85-.93 3-run-exh", lambda e: base(e) and e["p1_same"] is True and e["p2_same"] is True)
    show("F1a ref 19/23 .90-.93", lambda e: not e["weak"] and not e["skip"] and e["hour"] in (19, 23) and 0.90 <= e["pos"] < 0.93)


if __name__ == "__main__":
    main()

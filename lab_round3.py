#!/usr/bin/env python3
"""Round 3: surgical SWAP hunt.
CUTs: adopt only if BOTH splits negative (n_TR>=300).
ADDs: adopt only if TRAIN>0 & HO>0 & 3/3 months (prefer WR>59.6% accretive).
Final combo must keep n>=MFv2 floor AND raise WR (lab-verified)."""
import sys
sys.path.insert(0, ".")
from forensics_mfv2 import build_v2
from lab_momentum import load, HOLDOUT_START
from datetime import datetime, timezone

PAYOUT = 0.85
SKIP = {3, 20, 21, 22}
WEAK = {8, 9, 10, 11, 13, 14}


def main():
    sigs, allc, rows = build_v2()

    def res(rows_, i, d):
        en = rows_[i]["open"]
        ep = rows_[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def ev_pool(pool, name):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for e in pool:
            r = e["result"]
            idx = 0 if r == "WIN" else (2 if r == "DRAW" else 1)
            bk[e["split"]][idx] += 1
            bk[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[e["month"]]][idx] += 1
        return bk

    def ev_add(cond):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for e in allc:
            if e["flat"] or e["doji"]:
                continue
            try:
                if not cond(e):
                    continue
            except (KeyError, TypeError):
                continue
            d = "PUT" if e["bull"] else "CALL"
            r = res(rows, e["i"], d)
            idx = 0 if r == "WIN" else (2 if r == "DRAW" else 1)
            bk["HO" if e["ts"] >= HOLDOUT_START else "TR"][idx] += 1
            m = datetime.fromtimestamp(e["ts"], tz=timezone.utc).strftime("%Y-%m")
            bk[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][idx] += 1
        return bk

    def show(name, bk):
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = bk[k][0], bk[k][1], bk[k][2]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l)
        t, h = row["TR"], row["HO"]
        tag = ""
        if t[2] < 0 and h[2] < 0 and t[0] >= 300:
            tag = "CUTTABLE"
        elif t[2] > 0 and h[2] > 0:
            tag = "✅" if (row["J"][2] > 0 and row["A"][2] > 0 and row["S"][2] > 0) else "~2/3"
        print(f"{tag:>8s} {name:26s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} | J{row['J'][2]:+7.1f} A{row['A'][2]:+7.1f} S{row['S'][2]:+7.1f}")
        return row

    print("== CUT candidates (need BOTH negative) ==")
    normid = [s for s in sigs if not s["skip"] and 0.93 <= s["pos"] < 0.96]
    print(f"(normal 0.93-0.96 pool: {len(normid)})")
    show("N9 storm+mid", ev_pool([s for s in normid if s["atr_pct"] >= 0.8], "x"))
    show("N10 bigbody+mid", ev_pool([s for s in normid if s["body_atr"] >= 1.0], "x"))
    show("N11 h12/15+mid", ev_pool([s for s in normid if s["hour"] in (12, 15)], "x"))
    show("N12 run3+mid", ev_pool([s for s in normid if s["run"] >= 3], "x"))
    show("N13 h6/7+mid", ev_pool([s for s in normid if s["hour"] in (6, 7)], "x"))
    show("N14 h16-18+mid?", ev_pool([s for s in normid if s["hour"] in (16, 17, 18)], "x"))
    show("E1 v2 CALL", ev_pool([s for s in sigs if s["dir"] == "CALL"], "x"))
    show("E2 v2 PUT", ev_pool([s for s in sigs if s["dir"] == "PUT"], "x"))

    print("\n== ADD candidates (need TRAIN>0 & HO>0 & 3/3) ==")
    show("N1 night .85-.93", ev_add(lambda e: not e["weak"] and not e["skip"] and e["hour"] in (0, 1, 2, 4, 5, 6, 7) and 0.85 <= e["pos"] < 0.93))
    show("N2 hr19/23 .80-.85", ev_add(lambda e: not e["weak"] and not e["skip"] and e["hour"] in (19, 23) and 0.80 <= e["pos"] < 0.85))
    show("N3 skip .70-.75", ev_add(lambda e: e["skip"] and 0.70 <= e["pos"] < 0.75))
    show("N7 PUT .90-.93", ev_add(lambda e: not e["weak"] and not e["skip"] and e["bull"] and 0.90 <= e["pos"] < 0.93))
    show("N8 CALL .90-.93", ev_add(lambda e: not e["weak"] and not e["skip"] and e["bear"] and 0.90 <= e["pos"] < 0.93))
    show("A2d recheck 19/23 .85-.93", ev_add(lambda e: not e["weak"] and not e["skip"] and e["hour"] in (19, 23) and 0.85 <= e["pos"] < 0.93))
    show("H3 recheck skip .75-.80", ev_add(lambda e: e["skip"] and 0.75 <= e["pos"] < 0.80))
    show("N15 night .80-.85?", ev_add(lambda e: not e["weak"] and not e["skip"] and e["hour"] in (0, 1, 2, 4, 5, 6, 7) and 0.80 <= e["pos"] < 0.85))


if __name__ == "__main__":
    main()

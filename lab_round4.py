#!/usr/bin/env python3
"""Round 4: accretive-add refinement + flip-pocket hunt (2-way interactions).
Adopt: adds only if WR-accretive validated; flips only if BOTH splits <50%."""
import sys
sys.path.insert(0, ".")
from forensics_mfv2 import build_v2
from lab_momentum import HOLDOUT_START
from datetime import datetime, timezone

PAYOUT = 0.85


def main():
    sigs, allc, rows = build_v2()
    S = {(e["i"]): e for e in sigs}
    sig_idx = sorted(S.keys())
    prev_gap = {}
    prev_dir = {}
    last_i, last_d = None, None
    for i in sig_idx:
        prev_gap[i] = (i - last_i) if last_i is not None else 999
        prev_dir[i] = last_d
        last_i, last_d = i, S[i]["dir"]

    def res(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    def show_pool(name, pool):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0]}
        for e in pool:
            r = e["result"]
            bk[e["split"]][0 if r == "WIN" else (2 if r == "DRAW" else 1)] += 1
        t, h = bk["TR"], bk["HO"]
        for sp, b in (("TR", t), ("HO", h)):
            w, l, dr = b
            nn = w + l
            print(f"  {name:28s} {sp}: n={w+l+dr:5d} WR={100*w/nn if nn else 0:5.2f}% ${w*PAYOUT-l:+8.1f}")

    def show_add(name, cond):
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
        out = []
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = bk[k]
            nn = w + l
            out.append((w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l))
        t, h = out[0], out[1]
        print(f"  {name:28s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} | J{out[2][2]:+7.1f} A{out[3][2]:+7.1f} S{out[4][2]:+7.1f}")

    print("== F1/F2: add refinement ==")
    show_add("F1a 19/23 .90-.93", lambda e: not e["weak"] and not e["skip"] and e["hour"] in (19, 23) and 0.90 <= e["pos"] < 0.93)
    show_add("F1b 19/23 .85-.90", lambda e: not e["weak"] and not e["skip"] and e["hour"] in (19, 23) and 0.85 <= e["pos"] < 0.90)
    show_add("F2a skip h3 .75-.80", lambda e: e["hour"] == 3 and 0.75 <= e["pos"] < 0.80)
    show_add("F2b skip h20-22 .75-.80", lambda e: e["hour"] in (20, 21, 22) and 0.75 <= e["pos"] < 0.80)

    print("\n== F3-F9: flip hunt (need BOTH <50%) ==")
    show_pool("F3 storm+run3+", [s for s in sigs if s["atr_pct"] >= 0.8 and s["run"] >= 3])
    show_pool("F4 storm+bigbody", [s for s in sigs if s["atr_pct"] >= 0.8 and s["body_atr"] >= 1.0])
    show_pool("F5 storm+h12/15", [s for s in sigs if s["atr_pct"] >= 0.8 and s["hour"] in (12, 15)])
    show_pool("F6a gap<5min", [s for s in sigs if prev_gap[s["i"]] < 5])
    show_pool("F6b gap 5-30", [s for s in sigs if 5 <= prev_gap[s["i"]] <= 30])
    show_pool("F6c gap>30min", [s for s in sigs if prev_gap[s["i"]] > 30])
    show_pool("F8 prev-big", [s for s in sigs if s["p1_body_atr"] >= 2.0])
    show_pool("F9a same-as-prev", [s for s in sigs if prev_dir[s["i"]] == s["dir"]])
    show_pool("F9b changed-vs-prev", [s for s in sigs if prev_dir[s["i"]] is not None and prev_dir[s["i"]] != s["dir"]])
    # F7 round number: need close price -> recover from rows via i-1
    def near_round(s, grid=0.001, tol=0.0005):
        cc = rows[s["i"] - 1]["close"]
        return abs(cc - round(cc / grid) * grid) < tol
    show_pool("F7a near-round", [s for s in sigs if near_round(s)])
    show_pool("F7b off-round", [s for s in sigs if not near_round(s)])


if __name__ == "__main__":
    main()

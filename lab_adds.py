#!/usr/bin/env python3
"""Round 2: ADD-back tests (count must stay >= MFv2 floor) + flip-pocket hunt.
Each candidate: TRAIN/HO + months. Adopt only if TRAIN>0 & HO>0 (& ideally 3/3)."""
import sys
sys.path.insert(0, ".")
from forensics_mfv2 import build_v2
from lab_momentum import load
from datetime import datetime, timezone

PAYOUT = 0.85
SKIP = {3, 20, 21, 22}
WEAK = {8, 9, 10, 11, 13, 14}


def outcome(rows, i, d):
    en = rows[i]["open"]
    ep = rows[i + 1]["open"]
    return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")


def main():
    sigs, allc, rows = build_v2()
    Acc = {e["i"]: e for e in allc}

    def ev(name, cond, direction=None):
        """direction(e)->CALL/PUT or None=fade color. Returns per-split stats."""
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for e in allc:
            if e["flat"] or e["doji"]:
                if not (name.startswith("DJI")):
                    continue
            try:
                if not cond(e):
                    continue
            except (KeyError, TypeError):
                continue
            if direction:
                d = direction(e)
            else:
                d = "PUT" if e["bull"] else ("CALL" if e["bear"] else None)
            if d is None:
                continue
            r = outcome(rows, e["i"], d)
            idx = 0 if r == "WIN" else (2 if r == "DRAW" else 1)
            bk["HO" if e["ts"] >= __import__("lab_momentum").HOLDOUT_START else "TR"][idx] += 1
            m = datetime.fromtimestamp(e["ts"], tz=timezone.utc).strftime("%Y-%m")
            bk[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][idx] += 1
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = bk[k][0], bk[k][1], bk[k][2]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l)
        return row

    C = {
        # C: weak-hour add-back with v2 thresholds
        "C1 weak+v2thr": (lambda e: e["weak"] and not e["doji"] and not e["flat"] and
                          e["pos"] >= (0.80 if e["skip"] else 0.93), None),
        # A1: weak-hour ultra only
        "A1a weak+pos.96": (lambda e: e["weak"] and e["pos"] >= 0.96, None),
        "A1b weak+pos.98": (lambda e: e["weak"] and e["pos"] >= 0.98, None),
        # A2: normal 0.85-0.93 rescue pockets (non-weak, non-skip)
        "A2a .85-.93 calm": (lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93 and e["atr_pct"] < 0.5, None),
        "A2b .85-.93 body<.5atr": (lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93 and e["body_atr"] < 0.5, None),
        "A2c .85-.93 rng%<.5": (lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93 and e["range_pct"] < 0.5, None),
        "A2d .85-.93 hr19-23": (lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93 and e["hour"] in (19, 23), None),
        "A2e .85-.93 run==1": (lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93 and e["run"] == 1, None),
        "A2f .90-.93 plain": (lambda e: not e["weak"] and not e["skip"] and 0.90 <= e["pos"] < 0.93, None),
        "A2g .85-.93+calm+body": (lambda e: not e["weak"] and not e["skip"] and 0.85 <= e["pos"] < 0.93 and e["atr_pct"] < 0.5 and e["body_atr"] < 0.5, None),
        # A4: doji fade-the-run
        "DJIa doji+run>=2": (lambda e: True, None),  # placeholder replaced below
        # H: skip tuning
        "H1 skip h=3 .80-.85": (lambda e: e["hour"] == 3 and 0.80 <= e["pos"] < 0.85, None),
        "H2 skip h20-22 .80-.85": (lambda e: e["hour"] in (20, 21, 22) and 0.80 <= e["pos"] < 0.85, None),
        "H3 skip .75-.80": (lambda e: e["skip"] and 0.75 <= e["pos"] < 0.80, None),
    }
    # doji special: fade direction of the run (prev non-doji color)
    def doji_dir(e):
        return None  # need run color; handled via run proxy below
    # replace DJI with explicit loop (needs prev color: bull of run => fade PUT)
    print(f"{'candidate':22s} | {'TRAIN n':>7s} {'WR':>6s} {'net$':>8s} | {'HO n':>6s} {'WR':>6s} {'net$':>8s} | {'Jul$':>7s} {'Aug$':>7s} {'Sep$':>7s}")
    for name, (cond, _) in C.items():
        if name.startswith("DJI"):
            continue
        r = ev(name, cond)
        t, h = r["TR"], r["HO"]
        ok = "✅" if t[2] > 0 and h[2] > 0 else "  "
        print(f"{ok}{name:20s} | {t[0]:7d} {t[1]:5.2f}% {t[2]:+8.1f} | {h[0]:6d} {h[1]:5.2f}% {h[2]:+8.1f} | {r['J'][2]:+7.1f} {r['A'][2]:+7.1f} {r['S'][2]:+7.1f}")

    # DJI explicit: doji candles, fade the prevailing run color
    print("\n-- doji tests --")
    for name, minrun in (("DJIa doji fade run>=2", 2), ("DJIb doji fade run>=3", 3)):
        bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        import lab_momentum as LM
        for e in allc:
            if not e["doji"] or e["flat"] or e["weak"]:
                continue
            # run color before doji: walk back
            i = e["i"]
            rb = None
            cnt = 0
            j = i - 2
            while j >= 0:
                c = rows[j]
                if c["close"] == c["open"]:
                    break
                b = c["close"] > c["open"]
                if rb is None:
                    rb = b
                if b != rb:
                    break
                cnt += 1
                j -= 1
            if rb is None or cnt < minrun:
                continue
            d = "PUT" if rb else "CALL"  # fade the run
            r = outcome(rows, i, d)
            idx = 0 if r == "WIN" else (2 if r == "DRAW" else 1)
            bk["HO" if e["ts"] >= LM.HOLDOUT_START else "TR"][idx] += 1
            m = datetime.fromtimestamp(e["ts"], tz=timezone.utc).strftime("%Y-%m")
            bk[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][idx] += 1
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = bk[k][0], bk[k][1], bk[k][2]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l)
        t, h = row["TR"], row["HO"]
        ok = "✅" if t[2] > 0 and h[2] > 0 else "  "
        print(f"{ok}{name:20s} | {t[0]:7d} {t[1]:5.2f}% {t[2]:+8.1f} | {h[0]:6d} {h[1]:5.2f}% {h[2]:+8.1f} | {row['J'][2]:+7.1f} {row['A'][2]:+7.1f} {row['S'][2]:+7.1f}")

    # G: 0.96-0.98 deep dive (TRAIN dip) — hunt sub-50% flip pockets
    print("\n-- G: 0.96-0.98 TRAIN-dip autopsy --")
    sub = [s for s in sigs if 0.96 <= s["pos"] < 0.98]
    for gname, cond in [
        ("weak? (none, trimmed)", lambda s: s["weak"]),
        ("storm", lambda s: s["atr_pct"] >= 0.8),
        ("calm", lambda s: s["atr_pct"] < 0.5),
        ("hr 12/15", lambda s: s["hour"] in (12, 15)),
        ("hr 0-7", lambda s: s["hour"] in (0, 1, 2, 4, 5, 6, 7)),
        ("body>=1atr", lambda s: s["body_atr"] >= 1.0),
        ("body<0.5atr", lambda s: s["body_atr"] < 0.5),
        ("run>=3", lambda s: s["run"] >= 3),
        ("run==1", lambda s: s["run"] == 1),
        ("CALL", lambda s: s["dir"] == "CALL"),
        ("PUT", lambda s: s["dir"] == "PUT"),
    ]:
        for sp in ("TR", "HO"):
            ss = [s for s in sub if s["split"] == sp and cond(s)]
            if not ss:
                continue
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            print(f"  {gname:18s} {sp}: n={len(ss):4d} WR={100*w/nn if nn else 0:5.2f}% ${w*PAYOUT-l:+7.1f}")


if __name__ == "__main__":
    main()

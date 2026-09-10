#!/usr/bin/env python3
"""COMB Phase 1: exhaustive candle-morphology forensics on MS2-lab pool.
Fixed a-priori buckets. Flags: both-neg (CUT? n_TR>=200), both-sub50 (FLIP? n_TR>=200).
NO volume (per user: morphology first)."""
import sys
sys.path.insert(0, ".")
from lab_final import build_pool
from lab_momentum import HOLDOUT_START

PAYOUT = 0.85


def build_ms2():
    ms1, allc, rows, vr, bull, c1 = build_pool()
    base_idx = {s["i"] for s in ms1}

    def res60(i, d):
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")

    ms2 = [s for s in ms1 if s["hour"] not in (12, 15)]
    for e in allc:
        if e["i"] in base_idx or e["flat"] or e["doji"]:
            continue
        v = vr[e["i"] - 1]
        if not (not e["weak"] and not e["skip"] and v is not None and v < c1 and 0.85 <= e["pos"] < 0.90):
            continue
        d = "PUT" if e["bull"] else "CALL"
        ms2.append({"i": e["i"], "ts": e["ts"], "hour": e["hour"], "pos": e["pos"], "dir": d,
                    "result": res60(e["i"], d), "split": "HO" if e["ts"] >= HOLDOUT_START else "TR",
                    "skip": e["skip"]})
    ms2.sort(key=lambda s: s["i"])
    return ms2, rows


def features(ms2, rows):
    n = len(rows)
    atr = [None] * n
    for i in range(60, n):
        atr[i] = sum(rows[j]["high"] - rows[j]["low"] for j in range(i - 59, i + 1)) / 60
    for s in ms2:
        k = s["i"] - 1
        c, p = rows[k], rows[k - 1] if k >= 1 else None
        rng = c["high"] - c["low"]
        body = abs(c["close"] - c["open"])
        bull = c["close"] > c["open"]
        a = atr[k]
        s["range_atr"] = rng / a if a else None
        s["body_atr"] = body / a if a else None
        s["body_ratio"] = body / rng if rng > 0 else 0
        hi, lo = max(c["close"], c["open"]), min(c["close"], c["open"])
        s["up_wick"] = (c["high"] - hi) / rng if rng > 0 else 0
        s["lo_wick"] = (lo - c["low"]) / rng if rng > 0 else 0
        s["close_wick"] = s["up_wick"] if bull else s["lo_wick"]
        s["open_wick"] = s["lo_wick"] if bull else s["up_wick"]
        s["open_pos"] = ((c["open"] - c["low"]) / rng if bull else (c["high"] - c["open"]) / rng) if rng > 0 else 0.5
        s["atr60"] = a
        if p and a:
            s["gap_atr"] = (c["open"] - p["close"]) / a
            pb = abs(p["close"] - p["open"])
            ph, pl = max(p["close"], p["open"]), min(p["close"], p["open"])
            bullprev = p["close"] > p["open"]
            s["p1_body_atr"] = pb / a
            s["engulf"] = ("bull" if (bull and not bullprev and c["close"] > ph and c["open"] < pl)
                           else ("bear" if ((not bull) and bullprev and c["close"] < pl and c["open"] > ph) else "none"))
            s["hhll"] = ("HH" if c["high"] > p["high"] else "LH") + ("HL" if c["low"] > p["low"] else "LL")
        else:
            s["gap_atr"], s["p1_body_atr"], s["engulf"], s["hhll"] = None, None, "none", "??"
        # run + runup
        run, j = 1, k - 1
        while j >= 0 and (rows[j]["close"] > rows[j]["open"]) == bull and rows[j]["close"] != rows[j]["open"]:
            run += 1
            j -= 1
        s["run"] = run
        start_o = rows[j + 1]["open"]
        s["runup"] = abs(c["close"] - start_o) / a if a else None
        # donch + bars-since-20-extreme
        if k >= 20:
            win = rows[k - 19:k + 1]
            hh = max(r["high"] for r in win)
            ll = min(r["low"] for r in win)
            s["donch"] = (c["close"] - ll) / (hh - ll) if hh > ll else 0.5
            bs = 0
            for r in reversed(win):
                if r["high"] >= hh or r["low"] <= ll:
                    break
                bs += 1
            s["bars_sx"] = bs
        else:
            s["donch"], s["bars_sx"] = None, None
    return atr


def main():
    ms2, rows = build_ms2()
    features(ms2, rows)
    W = sum(1 for s in ms2 if s["result"] == "WIN")
    L = sum(1 for s in ms2 if s["result"] == "LOSS")
    print(f"MS2-lab: n={len(ms2)} W={W} L={L} WR={100*W/(W+L):.2f}% net={W*PAYOUT-L:+.1f}")
    tr_atr = sorted(s["atr60"] for s in ms2 if s["atr60"] is not None and s["split"] == "TR")
    a1, a2 = tr_atr[len(tr_atr) // 3], tr_atr[2 * len(tr_atr) // 3]
    print(f"ATR terciles (TRAIN-frozen): {a1:.6f}/{a2:.6f}")

    def show(name, pool):
        o = []
        for sp in ("TR", "HO"):
            ss = [s for s in pool if s["split"] == sp]
            w = sum(1 for s in ss if s["result"] == "WIN")
            l = sum(1 for s in ss if s["result"] == "LOSS")
            nn = w + l
            o.append((len(ss), 100 * w / nn if nn else 0, w * PAYOUT - l, w, l))
        t, h = o[0], o[1]
        flag = ""
        if t[1] < 50 and h[1] < 50 and t[0] >= 200:
            flag = "FLIP?"
        elif t[2] < 0 and h[2] < 0 and t[0] >= 200:
            flag = "CUT?"
        print(f"{flag:5s} {name:26s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} (W{t[3]}/L{t[4]}) | HO n={h[0]:4d} {h[1]:5.2f}% {h[2]:+7.1f} (W{h[3]}/L{h[4]})")

    F = [
        ("SIZE range_atr", "range_atr", [("<0.5", lambda x: x < 0.5), ("0.5-1", lambda x: 0.5 <= x < 1.0),
          ("1-1.5", lambda x: 1.0 <= x < 1.5), ("1.5-2.5", lambda x: 1.5 <= x < 2.5), (">2.5", lambda x: x >= 2.5)]),
        ("SIZE body_atr", "body_atr", [("<0.3", lambda x: x < 0.3), ("0.3-0.6", lambda x: 0.3 <= x < 0.6),
          ("0.6-1", lambda x: 0.6 <= x < 1.0), (">1", lambda x: x >= 1.0)]),
        ("TYPE body_ratio", "body_ratio", [("<0.2", lambda x: x < 0.2), ("0.2-0.5", lambda x: 0.2 <= x < 0.5),
          ("0.5-0.8", lambda x: 0.5 <= x < 0.8), (">0.8", lambda x: x >= 0.8)]),
        ("WICK close_wick", "close_wick", [("<0.05", lambda x: x < 0.05), ("0.05-0.15", lambda x: 0.05 <= x < 0.15),
          (">0.15", lambda x: x >= 0.15)]),
        ("WICK open_wick", "open_wick", [("<0.05", lambda x: x < 0.05), ("0.05-0.15", lambda x: 0.05 <= x < 0.15),
          (">0.15", lambda x: x >= 0.15)]),
        ("OPEN open_pos", "open_pos", [("<0.2", lambda x: x < 0.2), ("0.2-0.5", lambda x: 0.2 <= x < 0.5),
          ("0.5-0.8", lambda x: 0.5 <= x < 0.8), (">0.8", lambda x: x >= 0.8)]),
        ("GAP gap_atr", "gap_atr", [("<-1", lambda x: x < -1), ("-1..-0.3", lambda x: -1 <= x < -0.3),
          ("flat", lambda x: -0.3 <= x <= 0.3), ("0.3..1", lambda x: 0.3 < x <= 1), (">1", lambda x: x > 1)]),
        ("RUNUP runup_atr", "runup", [("<1", lambda x: x < 1), ("1-2", lambda x: 1 <= x < 2),
          ("2-3", lambda x: 2 <= x < 3), (">3", lambda x: x >= 3)]),
        ("RUN len", "run", [("1", lambda x: x == 1), ("2", lambda x: x == 2),
          ("3-4", lambda x: 3 <= x <= 4), ("5+", lambda x: x >= 5)]),
        ("ENGULF", "engulf", [("bull", lambda x: x == "bull"), ("bear", lambda x: x == "bear"), ("none", lambda x: x == "none")]),
        ("HHLL", "hhll", [("HHHH", lambda x: x == "HHHH"), ("HHLL", lambda x: x == "HHLL"),
          ("LHHL", lambda x: x == "LHHL"), ("LHLL", lambda x: x == "LHLL")]),
        ("ATR abs", "atr60", [("low", lambda x: x < a1), ("mid", lambda x: a1 <= x <= a2), ("high", lambda x: x > a2)]),
        ("DONCH", "donch", [("<0.2", lambda x: x < 0.2), ("0.2-0.4", lambda x: 0.2 <= x < 0.4),
          ("0.4-0.6", lambda x: 0.4 <= x < 0.6), ("0.6-0.8", lambda x: 0.6 <= x < 0.8), (">0.8", lambda x: x >= 0.8)]),
        ("BARS-SX", "bars_sx", [("0-2", lambda x: x <= 2), ("3-9", lambda x: 3 <= x <= 9), ("10+", lambda x: x >= 10)]),
        ("P1BODY", "p1_body_atr", [("<0.5", lambda x: x < 0.5), ("0.5-1", lambda x: 0.5 <= x < 1.0), (">1", lambda x: x >= 1.0)]),
    ]
    for title, key, buckets in F:
        print(f"\n== {title} ==")
        for nm, cond in buckets:
            show(f"{key} {nm}", [s for s in ms2 if s[key] is not None and cond(s[key])])
    # direction-split wick check
    print("\n== WICK x DIRECTION ==")
    show("PUT close_wick>.15", [s for s in ms2 if s["dir"] == "PUT" and s["close_wick"] > 0.15])
    show("PUT close_wick<.05", [s for s in ms2 if s["dir"] == "PUT" and s["close_wick"] < 0.05])
    show("CALL close_wick>.15", [s for s in ms2 if s["dir"] == "CALL" and s["close_wick"] > 0.15])
    show("CALL close_wick<.05", [s for s in ms2 if s["dir"] == "CALL" and s["close_wick"] < 0.05])


if __name__ == "__main__":
    main()

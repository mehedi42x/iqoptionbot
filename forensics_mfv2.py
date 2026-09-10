#!/usr/bin/env python3
"""Round 1: MFv2 (W7) loser forensics with EXTENDED features. TRAIN vs HO."""
import sys
sys.path.insert(0, ".")
from lab_momentum import load, features, HOLDOUT_START, WARM
from datetime import datetime, timezone

PAYOUT = 0.85
SKIP = {3, 20, 21, 22}
WEAK = {8, 9, 10, 11, 13, 14}


def build_v2():
    rows = load()
    F = features(rows)
    n = len(rows)
    closes = [c["close"] for c in rows]
    atrs = [None] * n
    for i in range(15, n):
        trs = []
        for t in range(i - 14, i):
            cur, prv = rows[t], rows[t - 1]
            trs.append(max(cur["high"] - cur["low"], abs(cur["high"] - prv["close"]),
                           abs(cur["low"] - prv["close"])))
        atrs[i] = sum(trs) / 14
    sigs = []
    allc = []  # every evaluated candle (for ADD forklift analysis)
    for i in range(WARM, n - 1):
        f = F[i]
        k = rows[i - 1]
        rng = k["high"] - k["low"]
        o, h, l, cc = k["open"], k["high"], k["low"], k["close"]
        body = abs(cc - o)
        up_w = (h - max(o, cc)) / rng if rng > 0 else 0
        lo_w = (min(o, cc) - l) / rng if rng > 0 else 0
        atr = atrs[i]
        hist = [a for a in atrs[max(15, i - 60):i] if a]
        rhist = [rows[t]["high"] - rows[t]["low"] for t in range(max(1, i - 60), i)]
        hh20 = max(rows[t]["high"] for t in range(max(0, i - 21), i - 1)) if i - 21 >= 0 else None
        ll20 = min(rows[t]["low"] for t in range(max(0, i - 21), i - 1)) if i - 21 >= 0 else None
        p1 = rows[i - 2] if i - 2 >= 0 else None
        p2 = rows[i - 3] if i - 3 >= 0 else None
        bull = cc > o
        entry = {"i": i, "ts": rows[i]["ts"], "pos": f["pos_col"], "hour": f["hour"],
                 "bull": bull, "bear": cc < o, "doji": cc == o, "flat": rng <= 0,
                 "body_ratio": f["body_ratio"], "range_atr": (rng / atr) if atr else 0,
                 "up_wick": up_w, "lo_wick": lo_w,
                 "body_atr": (body / atr) if atr else 0,
                 "donch20": ((cc - ll20) / (hh20 - ll20)) if hh20 and hh20 > ll20 else 0.5,
                 "range_pct": (sum(1 for r in rhist if r < rng) / len(rhist)) if rhist else 0.5,
                 "atr_pct": (sum(1 for a in hist if a < atr) / len(hist)) if hist and atr else 0.5,
                 "rsi3": f.get("rsi3"), "rsi14": f.get("rsi14"),
                 "mom1": f.get("mom1", 0) / atr if atr else 0,
                 "mom5": f.get("mom5", 0) / atr if atr else 0,
                 "run": f["run"],
                 "p1_same": ((p1["close"] > p1["open"]) == bull) if p1 and not entry_doji(p1) else None,
                 "p1_body_atr": (abs(p1["close"] - p1["open"]) / atr) if (p1 and atr) else 0,
                 "p2_same": ((p2["close"] > p2["open"]) == bull) if p2 and not entry_doji(p2) else None,
                 "minute": datetime.fromtimestamp(k["ts"], tz=timezone.utc).minute,
                 "skip": f["hour"] in SKIP, "weak": f["hour"] in WEAK}
        allc.append(entry)
        # MFv2 rule
        if entry["weak"] or entry["flat"] or entry["doji"]:
            continue
        if entry["skip"]:
            thr = 0.80
        else:
            thr = 0.93
        if entry["pos"] < thr:
            continue
        d = "PUT" if bull else "CALL"
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        r = "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")
        m = datetime.fromtimestamp(rows[i]["ts"], tz=timezone.utc).strftime("%Y-%m")
        entry.update({"dir": d, "result": r, "month": m,
                      "split": "HO" if rows[i]["ts"] >= HOLDOUT_START else "TR"})
        sigs.append(entry)
    return sigs, allc, rows


def entry_doji(c):
    return c["close"] == c["open"]


def show(sigs, title, groups):
    print(f"\n== {title} ==")
    for gname, cond in groups:
        for sp in ("TR", "HO"):
            sub = [s for s in sigs if s["split"] == sp and cond(s)]
            w = sum(1 for s in sub if s["result"] == "WIN")
            l = sum(1 for s in sub if s["result"] == "LOSS")
            nn = w + l
            wr = 100 * w / nn if nn else 0
            flag = " <-- ?" if nn >= 200 and ((wr < 54.05 and sp == "TR") or abs(wr - 56) > 6) else ""
            print(f"  {gname:24s} {sp}: n={len(sub):5d} WR={wr:5.2f}% ${w*PAYOUT-l:+8.1f}{flag}")


def main():
    sigs, allc, rows = build_v2()
    print(f"MFv2 signals: {len(sigs)}")
    show(sigs, "pos fine buckets", [
        ("0.80-0.85(skip)", lambda s: s["skip"] and 0.80 <= s["pos"] < 0.85),
        ("0.85-0.90(skip)", lambda s: s["skip"] and 0.85 <= s["pos"] < 0.90),
        ("0.90-0.93(skip)", lambda s: s["skip"] and 0.90 <= s["pos"] < 0.93),
        ("0.93-0.96", lambda s: 0.93 <= s["pos"] < 0.96),
        ("0.96-0.98", lambda s: 0.96 <= s["pos"] < 0.98),
        ("0.98-1.01", lambda s: 0.98 <= s["pos"] <= 1.01),
    ])
    show(sigs, "wick structure (opp-side wick = against fade?)", [
        ("up_wick<0.05", lambda s: s["up_wick"] < 0.05),
        ("up_wick 0.05-0.15", lambda s: 0.05 <= s["up_wick"] < 0.15),
        ("up_wick>=0.15", lambda s: s["up_wick"] >= 0.15),
        ("lo_wick<0.05", lambda s: s["lo_wick"] < 0.05),
        ("lo_wick 0.05-0.15", lambda s: 0.05 <= s["lo_wick"] < 0.15),
        ("lo_wick>=0.15", lambda s: s["lo_wick"] >= 0.15),
    ])
    show(sigs, "fade vs opp-wick conflict", [
        ("PUT fade + big lo_wick>=.15", lambda s: s["dir"] == "PUT" and s["lo_wick"] >= 0.15),
        ("PUT fade + small lo_wick", lambda s: s["dir"] == "PUT" and s["lo_wick"] < 0.15),
        ("CALL fade + big up_wick>=.15", lambda s: s["dir"] == "CALL" and s["up_wick"] >= 0.15),
        ("CALL fade + small up_wick", lambda s: s["dir"] == "CALL" and s["up_wick"] < 0.15),
    ])
    show(sigs, "donchian20 position", [
        ("donch<0.2", lambda s: s["donch20"] < 0.2),
        ("donch 0.2-0.4", lambda s: 0.2 <= s["donch20"] < 0.4),
        ("donch 0.4-0.6", lambda s: 0.4 <= s["donch20"] <= 0.6),
        ("donch 0.6-0.8", lambda s: 0.6 < s["donch20"] <= 0.8),
        ("donch>0.8", lambda s: s["donch20"] > 0.8),
    ])
    show(sigs, "range percentile (60)", [
        ("rng%<0.2", lambda s: s["range_pct"] < 0.2),
        ("rng% 0.2-0.5", lambda s: 0.2 <= s["range_pct"] < 0.5),
        ("rng% 0.5-0.8", lambda s: 0.5 <= s["range_pct"] < 0.8),
        ("rng%>0.8", lambda s: s["range_pct"] >= 0.8),
    ])
    show(sigs, "3-candle pattern", [
        ("p1 same color", lambda s: s["p1_same"] is True),
        ("p1 opp color", lambda s: s["p1_same"] is False),
        ("p1+p2 same (3-run)", lambda s: s["p1_same"] is True and s["p2_same"] is True),
        ("p1 big body>=1atr", lambda s: s["p1_body_atr"] >= 1.0),
    ])
    show(sigs, "RSI3", [
        ("rsi3<15", lambda s: s["rsi3"] is not None and s["rsi3"] < 15),
        ("rsi3 15-40", lambda s: s["rsi3"] is not None and 15 <= s["rsi3"] < 40),
        ("rsi3 40-60", lambda s: s["rsi3"] is not None and 40 <= s["rsi3"] <= 60),
        ("rsi3 60-85", lambda s: s["rsi3"] is not None and 60 < s["rsi3"] <= 85),
        ("rsi3>85", lambda s: s["rsi3"] is not None and s["rsi3"] > 85),
    ])
    show(sigs, "vol regime + slope", [
        ("calm<0.2", lambda s: s["atr_pct"] < 0.2),
        ("0.2-0.5", lambda s: 0.2 <= s["atr_pct"] < 0.5),
        ("0.5-0.8", lambda s: 0.5 <= s["atr_pct"] < 0.8),
        ("storm>0.8", lambda s: s["atr_pct"] >= 0.8),
    ])
    show(sigs, "mom5 (fade vs 5c momentum)", [
        ("fade WITH mom5", lambda s: (s["mom5"] > 0) == (s["dir"] == "CALL") and s["mom5"] != 0),
        ("fade VS mom5", lambda s: (s["mom5"] > 0) != (s["dir"] == "CALL") and s["mom5"] != 0),
        ("mom5 huge>2atr", lambda s: abs(s["mom5"]) > 2.0),
    ])
    show(sigs, "body_atr", [
        ("body<0.5atr", lambda s: s["body_atr"] < 0.5),
        ("body 0.5-1atr", lambda s: 0.5 <= s["body_atr"] < 1.0),
        ("body>=1atr", lambda s: s["body_atr"] >= 1.0),
    ])


if __name__ == "__main__":
    main()

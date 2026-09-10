#!/usr/bin/env python3
"""
MaxFade FULL loser forensics: WHY did the 9,212 losses lose?
Features per signal; every bucket shown TRAIN vs HOLDOUT.
"""
import sys
sys.path.insert(0, ".")
from lab_momentum import load, features, HOLDOUT_START, WARM
from datetime import datetime, timezone

PAYOUT = 0.85
SKIP = {3, 20, 21, 22}


def ema_full(closes, period):
    e = sum(closes[:period]) / period
    a = 2.0 / (period + 1.0)
    out = [None] * period
    out_e = e
    res = [None] * len(closes)
    res[period - 1] = e
    for i in range(period, len(closes)):
        e = closes[i] * a + e * (1.0 - a)
        res[i] = e
    return res


def main():
    rows = load()
    F = features(rows)
    n = len(rows)
    closes = [c["close"] for c in rows]
    e9 = ema_full(closes, 9)
    e12 = ema_full(closes, 12)
    e50 = ema_full(closes, 50)
    # rolling ATR14 series for atr_pct (vol regime)
    atrs = [None] * n
    for i in range(15, n):
        trs = []
        for t in range(i - 14, i):
            cur, prv = rows[t], rows[t - 1]
            trs.append(max(cur["high"] - cur["low"], abs(cur["high"] - prv["close"]),
                           abs(cur["low"] - prv["close"])))
        atrs[i] = sum(trs) / 14

    sigs = []
    for i in range(WARM, n - 1):
        f = F[i]
        thr = 0.80 if f["hour"] in SKIP else 0.85
        if f["pos_col"] < thr:
            continue
        d = "PUT" if f["bull"] else ("CALL" if f["bear"] else None)
        if d is None:
            continue
        en = rows[i]["open"]
        ep = rows[i + 1]["open"]
        r = "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")
        k = i - 1
        ema_side = None
        if e9[k] is not None and e12[k] is not None and e9[k] != e12[k]:
            ema_side = "CALL" if e9[k] > e12[k] else "PUT"
        hist = [a for a in atrs[max(15, i - 60):i] if a]
        sigs.append({
            "split": "HO" if rows[i]["ts"] >= HOLDOUT_START else "TR",
            "result": r, "dir": d, "pos": f["pos_col"],
            "body": f["body_ratio"], "ratr": f.get("range_atr") or 0,
            "hour": f["hour"], "run": f["run"],
            "rsi3": f.get("rsi3"), "rsi14": f.get("rsi14"),
            "ema_side": ema_side,
            "aligned_ema": (ema_side == d) if ema_side else None,
            "ema50_side": ("CALL" if closes[k] > e50[k] else "PUT") if e50[k] else None,
            "atr_pct": (sum(1 for a in hist if a < atrs[i]) / len(hist)) if hist and atrs[i] else None,
            "skip": f["hour"] in SKIP,
            "mom5_atr": (f.get("mom5", 0) / f["atr"]) if f.get("atr") else 0,
        })
    print(f"signals: {len(sigs)} (FULL-mode replay)")

    def show(title, keyfn, groups):
        print(f"\n== {title} ==")
        for gname, cond in groups:
            for sp in ("TR", "HO"):
                sub = [s for s in sigs if s["split"] == sp and cond(s)]
                w = sum(1 for s in sub if s["result"] == "WIN")
                l = sum(1 for s in sub if s["result"] == "LOSS")
                nn = w + l
                wr = 100 * w / nn if nn else 0
                print(f"  {gname:22s} {sp}: n={len(sub):5d} WR={wr:5.2f}% ${w*PAYOUT-l:+8.1f}")

    show("pos buckets", None, [
        ("0.80-0.83", lambda s: 0.80 <= s["pos"] < 0.83),
        ("0.83-0.85", lambda s: 0.83 <= s["pos"] < 0.85),
        ("0.85-0.87", lambda s: 0.85 <= s["pos"] < 0.87),
        ("0.87-0.90", lambda s: 0.87 <= s["pos"] < 0.90),
        ("0.90-0.93", lambda s: 0.90 <= s["pos"] < 0.93),
        ("0.93-0.96", lambda s: 0.93 <= s["pos"] < 0.96),
        ("0.96-1.01", lambda s: 0.96 <= s["pos"] <= 1.01),
    ])
    show("body_ratio", None, [
        ("<0.3", lambda s: s["body"] < 0.3),
        ("0.3-0.5", lambda s: 0.3 <= s["body"] < 0.5),
        ("0.5-0.7", lambda s: 0.5 <= s["body"] < 0.7),
        ("0.7-1.0", lambda s: 0.7 <= s["body"] <= 1.0),
    ])
    show("range_atr", None, [
        ("<0.5", lambda s: s["ratr"] < 0.5),
        ("0.5-1.0", lambda s: 0.5 <= s["ratr"] < 1.0),
        ("1.0-1.5", lambda s: 1.0 <= s["ratr"] < 1.5),
        ("1.5-2.5", lambda s: 1.5 <= s["ratr"] < 2.5),
        (">=2.5", lambda s: s["ratr"] >= 2.5),
    ])
    show("EMA-cross alignment (fade dir vs EMA9/12 side)", None, [
        ("aligned w/ EMA", lambda s: s["aligned_ema"] is True),
        ("against EMA", lambda s: s["aligned_ema"] is False),
        ("EMA flat/none", lambda s: s["aligned_ema"] is None),
    ])
    show("EMA50 side (fade dir vs close-vs-EMA50)", None, [
        ("fade WITH ema50side", lambda s: s["ema50_side"] == s["dir"]),
        ("fade VS ema50side", lambda s: s["ema50_side"] != s["dir"]),
    ])
    show("run length", None, [
        ("run==1", lambda s: s["run"] == 1),
        ("run==2", lambda s: s["run"] == 2),
        ("run==3", lambda s: s["run"] == 3),
        ("run>=4", lambda s: s["run"] >= 4),
    ])
    show("RSI3 at signal", None, [
        ("rsi3<20", lambda s: s["rsi3"] is not None and s["rsi3"] < 20),
        ("rsi3 20-40", lambda s: s["rsi3"] is not None and 20 <= s["rsi3"] < 40),
        ("rsi3 40-60", lambda s: s["rsi3"] is not None and 40 <= s["rsi3"] <= 60),
        ("rsi3 60-80", lambda s: s["rsi3"] is not None and 60 < s["rsi3"] <= 80),
        ("rsi3>80", lambda s: s["rsi3"] is not None and s["rsi3"] > 80),
    ])
    show("vol regime (atr_pct)", None, [
        ("calm <0.25", lambda s: s["atr_pct"] is not None and s["atr_pct"] < 0.25),
        ("mid 0.25-0.75", lambda s: s["atr_pct"] is not None and 0.25 <= s["atr_pct"] <= 0.75),
        ("storm >0.75", lambda s: s["atr_pct"] is not None and s["atr_pct"] > 0.75),
    ])
    show("direction/module", None, [
        ("CALL", lambda s: s["dir"] == "CALL"),
        ("PUT", lambda s: s["dir"] == "PUT"),
        ("FADE_SKIP", lambda s: s["skip"]),
        ("FADE normal", lambda s: not s["skip"]),
    ])
    show("mom5/atr sign vs fade", None, [
        ("fade WITH mom5", lambda s: (s["mom5_atr"] > 0) == (s["dir"] == "CALL") and s["mom5_atr"] != 0),
        ("fade VS mom5", lambda s: (s["mom5_atr"] > 0) != (s["dir"] == "CALL") and s["mom5_atr"] != 0),
    ])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Feature sweep for v2: NEW live-compatible info (EMA50/100 trend context,
RSI14, run-length, ATR slope) used to FLIP v1 direction (count preserved).
Rule adoption requires: TRAIN gain > 0 AND HOLDOUT gain > 0, TRAIN n>=300.
Also: module x expiry x split table.
"""
import sys
sys.path.insert(0, ".")
from analyze_losers import load, replay, ema, atr

PAYOUT = 0.8


def rsi_wilder(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        ch = closes[-period - 1 + i] - closes[-period - 2 + i] if False else None
    # simple Wilder over last `period` changes ending at last close
    diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    ag = sum(d for d in diffs if d > 0) / period
    al = sum(-d for d in diffs if d < 0) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


def enrich(rows, feats):
    """Add big-context features. feats from replay() has rolling-window state implicitly;
    recompute here with full history (equivalent once window filled; fallback for early)."""
    closes_all = [c["close"] for c in rows]
    for f in feats:
        i = f["i"]
        if f.get("ema9") is None:
            continue
        # completed set as strategy sees it: last up-to-299 closes before rows[i]
        lo = max(0, i - 299)
        completed = closes_all[lo:i]
        k = rows[i - 1]
        if len(completed) >= 50:
            f["ema50"] = ema(completed, 50)
        if len(completed) >= 100:
            f["ema100"] = ema(completed, 100)
        f["rsi14"] = rsi_wilder(completed, 14)
        # run length of same color ending at k
        run = 1
        j = i - 1
        bull = k["close"] > k["open"]
        while j - 1 >= 0:
            p = rows[j - 1]
            pb = p["close"] > p["open"]
            if pb == bull and p["close"] != p["open"]:
                run += 1
                j -= 1
            else:
                break
        f["run_len"] = run
        # ATR slope: atr now vs 5 candles ago (needs window)
        if i - 5 >= 16:
            c0 = [{"high": rows[t]["high"], "low": rows[t]["low"], "close": rows[t]["close"]}
                  for t in range(max(0, i - 15 - 5), i - 5)]
            if len(c0) >= 15:
                f["atr5ago"] = atr(c0, 14)
        # ATR percentile rank in rolling window (volatility regime)
        if i >= 60:
            f["atr_pct"] = sum(1 for t in range(max(16, i - 60), i)
                               if True)  # placeholder, computed below
            hist = []
            for t in range(max(16, i - 60), i):
                cc = [{"high": rows[u]["high"], "low": rows[u]["low"], "close": rows[u]["close"]}
                      for u in range(max(0, t - 15), t)]
                if len(cc) >= 15:
                    hist.append(atr(cc, 14))
            if hist and f.get("atr"):
                below = sum(1 for a in hist if a < f["atr"])
                f["atr_pct"] = below / len(hist)
        # dist to ema50
        if f.get("ema50") and f.get("atr"):
            f["dist50_atr"] = (k["close"] - f["ema50"]) / f["atr"]
    return feats


def perf(rows, flip_cond):
    """(n, old_net, new_net, gain) applying flip where cond true."""
    w = l = 0
    nw = nl = 0
    n = 0
    for f in rows:
        r = f["v1_result"]
        if r not in ("WIN", "LOSS"):
            continue
        n += 1
        w += (r == "WIN")
        l += (r == "LOSS")
        rr = r
        if flip_cond(f):
            rr = "LOSS" if r == "WIN" else "WIN"
        nw += (rr == "WIN")
        nl += (rr == "LOSS")
    old = w * PAYOUT - l
    new = nw * PAYOUT - nl
    return n, old, new, new - old


def main():
    rows = load()
    feats = enrich(rows, replay(rows))
    sig = [f for f in feats if f["v1_signal"] and f.get("ema9") is not None
           and f["expiry_price"] is not None]
    TR = [f for f in sig if f["split"] == "TRAIN"]
    HO = [f for f in sig if f["split"] == "HOLDOUT"]
    # signal-sequence context (previous v1 signal + consecutive same-dir count)
    prev = None
    consec = 0
    for f in sorted(sig, key=lambda x: x["entry_ts"]):
        f["prev_sig"] = prev
        if prev == f["v1_signal"]:
            consec += 1
        else:
            consec = 0
        f["consec_same"] = consec
        prev = f["v1_signal"]

    print("== FLIP-RULE SWEEP (need TRAIN gain>0 AND HOLD gain>0, TRAIN n>=300) ==")
    rules = {
        # RSI overbought/oversold fade of MOMENTUM chase
        "MOM chase RSI>65/<35 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("rsi14") is not None and ((f["v1_signal"] == "CALL" and f["rsi14"] > 65) or (f["v1_signal"] == "PUT" and f["rsi14"] < 35)),
        "MOM chase RSI>70/<30 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("rsi14") is not None and ((f["v1_signal"] == "CALL" and f["rsi14"] > 70) or (f["v1_signal"] == "PUT" and f["rsi14"] < 30)),
        "MOM chase RSI>60/<40 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("rsi14") is not None and ((f["v1_signal"] == "CALL" and f["rsi14"] > 60) or (f["v1_signal"] == "PUT" and f["rsi14"] < 40)),
        # EMA50 conflict: MOM signal against bigger trend -> flip
        "MOM vs EMA50 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("ema50") is not None and ((f["v1_signal"] == "CALL") != (rows[f["i"] - 1]["close"] > f["ema50"])),
        "MOM vs EMA100 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("ema100") is not None and ((f["v1_signal"] == "CALL") != (rows[f["i"] - 1]["close"] > f["ema100"])),
        # run-length exhaustion
        "MOM run>=3 flip": lambda f: f["v1_module"] == "MOMENTUM" and (f.get("run_len") or 0) >= 3,
        "MOM run>=4 flip": lambda f: f["v1_module"] == "MOMENTUM" and (f.get("run_len") or 0) >= 4,
        "MOM run>=2 flip": lambda f: f["v1_module"] == "MOMENTUM" and (f.get("run_len") or 0) >= 2,
        # ATR falling (calm): momentum fails -> flip
        "MOM atr falling flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("atr5ago") and f["atr"] < f["atr5ago"],
        "MOM atr rising flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("atr5ago") and f["atr"] > f["atr5ago"] * 1.1,
        # far from EMA50 -> overextended -> flip MOM
        "MOM |dist50|>2 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("dist50_atr") is not None and abs(f["dist50_atr"]) > 2.0,
        "MOM |dist50|>1.5 flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("dist50_atr") is not None and abs(f["dist50_atr"]) > 1.5,
        # REVERSAL refinement: fade only if RSI confirms extreme, else follow trend
        "REV RSI mid 40-60 flip": lambda f: f["v1_module"] == "REVERSAL" and f.get("rsi14") is not None and 40 <= f["rsi14"] <= 60,
        "REV RSI mid 45-55 flip": lambda f: f["v1_module"] == "REVERSAL" and f.get("rsi14") is not None and 45 <= f["rsi14"] <= 55,
        "REV run>=3 flip": lambda f: f["v1_module"] == "REVERSAL" and (f.get("run_len") or 0) >= 3,
        # volatility regime: momentum needs volatility; fade needs calm?
        "MOM calm(atr%<30) flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("atr_pct") is not None and f["atr_pct"] < 0.30,
        "MOM calm(atr%<20) flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("atr_pct") is not None and f["atr_pct"] < 0.20,
        "REV storm(atr%>80) flip": lambda f: f["v1_module"] == "REVERSAL" and f.get("atr_pct") is not None and f["atr_pct"] > 0.80,
        # signal-sequence: repeated same-direction MOM chase = late?
        "MOM same-dir-as-prev flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("prev_sig") == f["v1_signal"],
        "MOM 2nd+consec flip": lambda f: f["v1_module"] == "MOMENTUM" and (f.get("consec_same") or 0) >= 1,
        "MOM 3rd+consec flip": lambda f: f["v1_module"] == "MOMENTUM" and (f.get("consec_same") or 0) >= 2,
        # hour-based (TRAIN worst MOM hours)
        "MOM hours{8,12,16,18} flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("hour") in (8, 12, 16, 18),
        "MOM hours{8,12,15,16,18} flip": lambda f: f["v1_module"] == "MOMENTUM" and f.get("hour") in (8, 12, 15, 16, 18),
    }
    for name, cond in rules.items():
        t = perf(TR, cond)
        h = perf(HO, cond)
        ok = "✅" if (t[3] > 0 and h[3] > 0 and t[0] >= 300) else ("~" if (t[3] > 0 and h[3] > 0) else "❌")
        print(f"  {ok} {name:28s} TRAIN n={t[0]:4d} gain={t[3]:+7.1f}R (old {t[1]:+7.1f}→new {t[2]:+7.1f}) | HO n={h[0]:3d} gain={h[3]:+6.1f}R")

    # ---- module x expiry x split (signal quality only, overlap ignored) ----
    print("\n== MODULE x EXPIRY x SPLIT (60/120/300, overlap ignored) ==")
    ts_idx = {c["ts"]: k for k, c in enumerate(rows)}
    for mod in ("MOMENTUM", "REVERSAL"):
        for exp in (60, 120, 300):
            for split, sname in ((TR, "TRAIN"), (HO, "HOLD")):
                w = l = d = 0
                for f in [x for x in split if x["v1_module"] == mod]:
                    et = f["entry_ts"] + exp
                    if et in ts_idx:
                        ep = rows[ts_idx[et]]["open"]
                    else:
                        continue
                    en = f["entry_price"]
                    dd = f["v1_signal"]
                    if (ep > en if dd == "CALL" else ep < en):
                        w += 1
                    elif ep == en:
                        d += 1
                    else:
                        l += 1
                n = w + l
                wr = 100 * w / n if n else 0
                print(f"  {mod:8s} {exp:3d}s {sname:5s}: n={w+l+d:4d} WR={wr:5.2f}% net={w*PAYOUT-l:+8.1f}R")


if __name__ == "__main__":
    main()

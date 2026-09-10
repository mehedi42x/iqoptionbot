#!/usr/bin/env python3
"""Test C (proper): full v1 filter stack MINUS hour filter, on hours {3,20,21,22}."""
import sys
sys.path.insert(0, ".")
from analyze_losers import load, replay

PAYOUT = 0.8


def main():
    feats = replay(load())
    skip = [f for f in feats if (f.get("ema9") is not None and f["expiry_price"] is not None
                                 and f["v1_reason"] == "SKIP_HOUR")]
    print(f"skip-hour candles: {len(skip)}")
    for sname, split in (("TRAIN", [f for f in skip if f["split"] == "TRAIN"]),
                         ("HOLD", [f for f in skip if f["split"] == "HOLDOUT"])):
        # full v1 stack except hour
        elig = [f for f in split
                if f["dir"] != "NEUTRAL"
                and f["bullish"] == (f["dir"] == "BULLISH")
                and f["range"] > 0 and (f["atr"] or 0) > 0
                and f["range_atr"] >= 1.2 and f["body_ratio"] >= 0.50]
        for mod, cond in (("MOM", lambda f: 0.60 <= f["pos"] <= 0.85),
                          ("REV", lambda f: f["pos"] >= 0.90)):
            sub = [f for f in elig if cond(f)]
            w = l = d = 0
            for f in sub:
                trend_call = (f["dir"] == "BULLISH")
                take_call = trend_call if mod == "MOM" else (not trend_call)
                ep, en = f["expiry_price"], f["entry_price"]
                if (ep > en if take_call else ep < en):
                    w += 1
                elif ep == en:
                    d += 1
                else:
                    l += 1
            n = w + l
            print(f"  {sname:5s} {mod}: n={len(sub):3d} WR={100*w/n if n else 0:5.2f}% net={w*PAYOUT-l:+7.1f}R")


if __name__ == "__main__":
    main()

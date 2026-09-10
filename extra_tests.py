#!/usr/bin/env python3
"""Three extra pre-registered tests (each judged on HOLDOUT):
A. REVERSAL bad-hour flip (TRAIN WR<52% REV hours)
B. MOMENTUM flip on ALL TRAIN<50% MOM hours (expanded set)
C. SKIP_HOURS liberation: run v1 signal logic on hours {3,20,21,22} (adds trades)
"""
import sys
sys.path.insert(0, ".")
from sweep_features import enrich
from analyze_losers import load, replay

PAYOUT = 0.8


def wr_net(rows):
    w = sum(1 for r in rows if r["v1_result"] == "WIN")
    l = sum(1 for r in rows if r["v1_result"] == "LOSS")
    n = w + l
    return (100 * w / n if n else 0, w * PAYOUT - l, len(rows))


def main():
    rows = load()
    feats = enrich(rows, replay(rows))
    sig = [f for f in feats if f["v1_signal"] and f.get("ema9") is not None
           and f["expiry_price"] is not None]
    TR = [f for f in sig if f["split"] == "TRAIN"]
    HO = [f for f in sig if f["split"] == "HOLDOUT"]

    # TRAIN hour WRs per module
    print("== TRAIN hour WR (MOM / REV) ==")
    mom_hours, rev_hours = {}, {}
    for hh in range(24):
        m = [f for f in TR if f["v1_module"] == "MOMENTUM" and f.get("hour") == hh]
        r = [f for f in TR if f["v1_module"] == "REVERSAL" and f.get("hour") == hh]
        if m:
            s = wr_net(m)
            mom_hours[hh] = s
            print(f"  MOM h={hh:2d}: WR={s[0]:5.2f}% net={s[1]:+7.1f}R n={s[2]:3d}")
    for hh in range(24):
        r = [f for f in TR if f["v1_module"] == "REVERSAL" and f.get("hour") == hh]
        if r:
            s = wr_net(r)
            rev_hours[hh] = s
    print("  REV hours TRAIN:")
    for hh, s in sorted(rev_hours.items()):
        print(f"  REV h={hh:2d}: WR={s[0]:5.2f}% net={s[1]:+7.1f}R n={s[2]:3d}")

    mom_set = tuple(h for h, s in mom_hours.items() if s[0] < 50.0)
    rev_set = tuple(h for h, s in rev_hours.items() if s[0] < 52.0)
    print(f"\nTest A REV flip-set (TRAIN<52%): {rev_set}")
    print(f"Test B MOM flip-set (TRAIN<50%): {mom_set}")

    def flip_gain(split, mod, hset):
        sub = [f for f in split if f["v1_module"] == mod and f.get("hour") in hset]
        w = sum(1 for f in sub if f["v1_result"] == "WIN")
        l = sum(1 for f in sub if f["v1_result"] == "LOSS")
        return len(sub), w * PAYOUT - l, l * PAYOUT - w

    for name, mod, hs in (("A: REV flip", "REVERSAL", rev_set), ("B: MOM flip", "MOMENTUM", mom_set)):
        t = flip_gain(TR, mod, hs)
        h = flip_gain(HO, mod, hs)
        print(f"{name} hours={hs}: TRAIN n={t[0]} old={t[1]:+.1f}R new={t[2]:+.1f}R gain={t[2]-t[1]:+.1f}R | "
              f"HOLD n={h[0]} old={h[1]:+.1f}R new={h[2]:+.1f}R gain={h[2]-h[1]:+.1f}R")

    # ---- Test C: skip-hour liberation ----
    print("\n== Test C: v1 logic on SKIP hours {3,20,21,22} ==")
    # Reconstruct: skip-hour candles that pass ALL v1 filters except hour.
    # replay() gives v1_reason; SKIP_HOUR rows are exactly those blocked only by hour.
    skip = [f for f in feats if (f["v1_signal"] is None and f.get("ema9") is not None
                                 and f["expiry_price"] is not None
                                 and f["v1_reason"] == "SKIP_HOUR")]
    print(f"skip-hour blocked candles: {len(skip)} (these passed every other v1 filter!)")
    # determine module+direction as v1 would (pos zones), since color/range/body passed
    for sname, split in (("TRAIN", [f for f in skip if f["split"] == "TRAIN"]),
                         ("HOLD", [f for f in skip if f["split"] == "HOLDOUT"])):
        for mod, cond in (("MOM", lambda f: 0.60 <= f["pos"] <= 0.85),
                          ("REV", lambda f: f["pos"] >= 0.90)):
            sub = [f for f in split if cond(f)]
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

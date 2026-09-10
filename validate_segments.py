#!/usr/bin/env python3
"""
Segment x Split consistency: does a TRAIN edge survive in HOLDOUT?
Also tests ADAPTIVE regime-flip (uses only past closed trades, no lookahead).
"""
import sys
sys.path.insert(0, ".")
from analyze_losers import load, replay

PAYOUT = 0.8


def wr_net(rows):
    w = sum(1 for r in rows if r["v1_result"] == "WIN")
    l = sum(1 for r in rows if r["v1_result"] == "LOSS")
    n = w + l
    return (100 * w / n if n else 0, w * PAYOUT - l, len(rows))


def main():
    feats = replay(load())
    sig = [f for f in feats if f["v1_signal"] and f.get("ema9") is not None
           and f["expiry_price"] is not None]
    TR = [f for f in sig if f["split"] == "TRAIN"]
    HO = [f for f in sig if f["split"] == "HOLDOUT"]

    print("== SEGMENT CONSISTENCY (TRAIN -> HOLDOUT, v1 direction) ==")
    print(f"  {'segment':30s} {'TRAIN WR':>9s} {'TRAIN net':>9s} {'n':>5s} | {'HO WR':>7s} {'HO net':>8s} {'n':>4s}  consistent?")
    segs = {
        "MOM range<1.5": lambda f: f["v1_module"] == "MOMENTUM" and f["range_atr"] < 1.5,
        "MOM range>=1.5": lambda f: f["v1_module"] == "MOMENTUM" and f["range_atr"] >= 1.5,
        "MOM pos>=0.80": lambda f: f["v1_module"] == "MOMENTUM" and f["pos"] >= 0.80,
        "MOM pos<0.80": lambda f: f["v1_module"] == "MOMENTUM" and f["pos"] < 0.80,
        "MOM |gap|<0.05": lambda f: f["v1_module"] == "MOMENTUM" and abs(f["ema_gap_atr"]) < 0.05,
        "MOM PUT": lambda f: f["v1_module"] == "MOMENTUM" and f["v1_signal"] == "PUT",
        "MOM CALL": lambda f: f["v1_module"] == "MOMENTUM" and f["v1_signal"] == "CALL",
        "REV pos>=0.96": lambda f: f["v1_module"] == "REVERSAL" and f["pos"] >= 0.96,
        "REV pos 0.90-0.93": lambda f: f["v1_module"] == "REVERSAL" and 0.90 <= f["pos"] < 0.93,
        "REV PUT": lambda f: f["v1_module"] == "REVERSAL" and f["v1_signal"] == "PUT",
        "REV CALL": lambda f: f["v1_module"] == "REVERSAL" and f["v1_signal"] == "CALL",
        "ALL MOMENTUM": lambda f: f["v1_module"] == "MOMENTUM",
        "ALL REVERSAL": lambda f: f["v1_module"] == "REVERSAL",
    }
    for name, cond in segs.items():
        t, h = wr_net([f for f in TR if cond(f)]), wr_net([f for f in HO if cond(f)])
        mark = "YES" if (t[0] < 52 and h[0] < 52) or (t[0] > 55 and h[0] > 55) else ("mix" if (t[0] - 53.5) * (h[0] - 53.5) > 0 else "NO!")
        print(f"  {name:30s} {t[0]:8.2f}% {t[1]:+8.1f}R {t[2]:5d} | {h[0]:6.2f}% {h[1]:+7.1f}R {h[2]:4d}  {mark}")

    # ---- dead-zone candidates x split ----
    print("\n== DEAD-ZONE candidates x split ==")
    dead = [f for f in feats if (f["v1_signal"] is None and f.get("ema9") is not None
                                 and f["expiry_price"] is not None
                                 and f["v1_reason"] == "CLOSE_POSITION_OUT_OF_ZONE")]

    def dz_perf(rows, direc):
        w = l = d = 0
        for f in rows:
            trend_call = (f["dir"] == "BULLISH")
            take_call = trend_call if direc == "trend" else (not trend_call)
            ep, en = f["expiry_price"], f["entry_price"]
            if (ep > en if take_call else ep < en):
                w += 1
            elif ep == en:
                d += 1
            else:
                l += 1
        n = w + l
        return (100 * w / n if n else 0, w * PAYOUT - l, len(rows))

    for name, cond, direc in [
        ("dz 0.85-0.875 fade", lambda f: 0.85 < f["pos"] < 0.875, "fade"),
        ("dz 0.875-0.90 fade", lambda f: 0.875 <= f["pos"] < 0.90, "fade"),
        ("dz pos<0.60 trend", lambda f: f["pos"] < 0.60, "trend"),
        ("dz 0.85-0.90 fade ALL", lambda f: 0.85 < f["pos"] < 0.90, "fade"),
    ]:
        t = dz_perf([f for f in dead if cond(f) and f["split"] == "TRAIN"], direc)
        h = dz_perf([f for f in dead if cond(f) and f["split"] == "HOLDOUT"], direc)
        print(f"  {name:24s} TRAIN {t[0]:5.2f}% {t[1]:+7.1f}R n={t[2]:4d} | HOLD {h[0]:5.2f}% {h[1]:+6.1f}R n={h[2]:3d}")

    # ---- ADAPTIVE regime flip: flip MOMENTUM when its recent WR is cold ----
    print("\n== ADAPTIVE regime-flip (MOMENTUM flipped when last-N MOM WR < thr) ==")
    print("   (uses only already-CLOSED past trades: no lookahead)")
    for N in (15, 25, 40):
        for thr in (0.45, 0.50):
            for split_rows, sname in ((TR, "TRAIN"), (HO, "HO"), (TR + HO, "FULL")):
                mom_hist = []   # 1/0 for closed MOM trades (draws skipped)
                net = 0.0
                flips = 0
                for f in sorted(split_rows, key=lambda x: x["entry_ts"]):
                    d = f["v1_signal"]
                    if f["v1_module"] == "MOMENTUM" and len(mom_hist) >= N:
                        recent = sum(mom_hist[-N:]) / N
                        if recent < thr:
                            d = "PUT" if d == "CALL" else "CALL"
                            flips += 1
                    ep, en = f["expiry_price"], f["entry_price"]
                    if (ep > en if d == "CALL" else ep < en):
                        net += PAYOUT
                        res = 1
                    elif ep == en:
                        res = None
                    else:
                        net -= 1.0
                        res = 0
                    if f["v1_module"] == "MOMENTUM" and res is not None:
                        # history records outcome of the direction ACTUALLY taken
                        mom_hist.append(res)
                base = wr_net(split_rows)
                print(f"  N={N:2d} thr={thr}: {sname:5s} net={net:+8.1f}R (base={base[1]:+7.1f}R) flips={flips}")
            print()


if __name__ == "__main__":
    main()

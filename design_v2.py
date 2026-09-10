#!/usr/bin/env python3
"""
Design v2 rules on TRAIN, validate on HOLDOUT.

Constraint from user: trade count must NOT decrease.
=> All v1 signals still trade; we only FLIP direction where losers dominate,
   and optionally ADD dead-zone trades (increases count).
"""
import sys
sys.path.insert(0, ".")
from analyze_losers import load, replay

PAYOUT = 0.8


def net_of(rows, direction_fn=None):
    """direction_fn(f) -> 'CALL'/'PUT' or None to keep v1. Returns (net, n)."""
    net, n = 0.0, 0
    for f in rows:
        d = direction_fn(f) if direction_fn else f["v1_signal"]
        if d is None:
            continue
        ep, en = f["expiry_price"], f["entry_price"]
        if ep is None:
            continue
        n += 1
        if (ep > en if d == "CALL" else ep < en):
            net += PAYOUT
        elif ep != en:
            net -= 1.0
    return net, n


def flip_rules(f, rcut, pcut, gcut):
    """Return possibly-flipped direction for v1 signals."""
    d = f["v1_signal"]
    if d is None:
        return None
    if f["v1_module"] == "MOMENTUM":
        if f["range_atr"] < rcut or f["pos"] >= pcut or abs(f["ema_gap_atr"]) < gcut:
            return "PUT" if d == "CALL" else "CALL"
    return d


def main():
    rows = load()
    feats = replay(rows)
    sig = [f for f in feats if f["v1_signal"] and f.get("ema9") is not None
           and f["expiry_price"] is not None]
    TRAIN = [f for f in sig if f["split"] == "TRAIN"]
    HOLD = [f for f in sig if f["split"] == "HOLDOUT"]
    base_tr, _ = net_of(TRAIN)
    base_ho, _ = net_of(HOLD)
    print(f"TRAIN base: {base_tr:+.1f}R (n={len(TRAIN)}) | HOLDOUT base: {base_ho:+.1f}R (n={len(HOLD)})")

    # ---- individual rule gains (TRAIN) ----
    print("\n== single-rule TRAIN gains ==")
    cands = {
        "MOM range_atr<1.5 flip": lambda f: f["v1_module"] == "MOMENTUM" and f["range_atr"] < 1.5,
        "MOM range_atr<1.4 flip": lambda f: f["v1_module"] == "MOMENTUM" and f["range_atr"] < 1.4,
        "MOM range_atr<1.6 flip": lambda f: f["v1_module"] == "MOMENTUM" and f["range_atr"] < 1.6,
        "MOM pos>=0.80 flip": lambda f: f["v1_module"] == "MOMENTUM" and f["pos"] >= 0.80,
        "MOM pos>=0.78 flip": lambda f: f["v1_module"] == "MOMENTUM" and f["pos"] >= 0.78,
        "MOM pos>=0.82 flip": lambda f: f["v1_module"] == "MOMENTUM" and f["pos"] >= 0.82,
        "MOM |gap|<0.05 flip": lambda f: f["v1_module"] == "MOMENTUM" and abs(f["ema_gap_atr"]) < 0.05,
        "MOM |gap|<0.10 flip": lambda f: f["v1_module"] == "MOMENTUM" and abs(f["ema_gap_atr"]) < 0.10,
        "MOM PUT flip": lambda f: f["v1_module"] == "MOMENTUM" and f["v1_signal"] == "PUT",
        "REV pos 0.90-0.93 flip": lambda f: f["v1_module"] == "REVERSAL" and 0.90 <= f["pos"] < 0.93,
        "REV body<0.6 flip": lambda f: f["v1_module"] == "REVERSAL" and f["body_ratio"] < 0.6,
    }
    for name, cond in cands.items():
        sub = [f for f in TRAIN if cond(f)]
        w = sum(1 for f in sub if f["v1_result"] == "WIN")
        l = sum(1 for f in sub if f["v1_result"] == "LOSS")
        d = len(sub) - w - l
        old = w * PAYOUT - l
        new = l * PAYOUT - w
        print(f"  {name:26s} n={len(sub):5d} old={old:+8.1f}R new={new:+8.1f}R gain={new-old:+7.1f}R")

    # ---- joint grid (small!) ----
    print("\n== joint grid TRAIN+HOLDOUT ==")
    best = None
    for rcut in (1.4, 1.5, 1.6):
        for pcut in (0.78, 0.80, 0.82):
            for gcut in (0.0, 0.05, 0.10):
                fn = lambda f, r=rcut, p=pcut, g=gcut: flip_rules(f, r, p, g)
                ntr, _ = net_of(TRAIN, fn)
                nho, _ = net_of(HOLD, fn)
                flips_tr = sum(1 for f in TRAIN if fn(f) != f["v1_signal"])
                tag = ""
                if best is None or (ntr + 0.0) > best[0]:
                    best = (ntr, rcut, pcut, gcut, nho)
                print(f"  r<{rcut} p>={pcut} g<{gcut}: TRAIN {ntr:+8.1f}R (flips={flips_tr}) HOLD {nho:+7.1f}R")
    print(f"\nBEST TRAIN: r<{best[1]} p>={best[2]} g<{best[3]} -> TRAIN {best[0]:+.1f}R, HOLDOUT {best[4]:+.1f}R")

    # ---- dead-zone refinement ----
    print("\n== dead-zone refinement (TRAIN) ==")
    dead = [f for f in feats if (f["v1_signal"] is None and f.get("ema9") is not None
                                 and f["split"] == "TRAIN" and f["expiry_price"] is not None
                                 and f["v1_reason"] == "CLOSE_POSITION_OUT_OF_ZONE")]
    for name, cond, direc in [
        ("dz 0.85-0.90 fade, range>=2.0", lambda f: 0.85 < f["pos"] < 0.90 and f["range_atr"] >= 2.0, "fade"),
        ("dz 0.85-0.90 fade, range 1.5-2", lambda f: 0.85 < f["pos"] < 0.90 and 1.5 <= f["range_atr"] < 2.0, "fade"),
        ("dz 0.85-0.90 fade, range<1.5", lambda f: 0.85 < f["pos"] < 0.90 and f["range_atr"] < 1.5, "fade"),
        ("dz 0.85-0.875 fade", lambda f: 0.85 < f["pos"] < 0.875, "fade"),
        ("dz 0.875-0.90 fade", lambda f: 0.875 <= f["pos"] < 0.90, "fade"),
        ("dz pos<0.60 trend", lambda f: f["pos"] < 0.60, "trend"),
        ("dz pos<0.55 trend", lambda f: f["pos"] < 0.55, "trend"),
        ("dz pos 0.55-0.60 trend", lambda f: 0.55 <= f["pos"] < 0.60, "trend"),
    ]:
        sub = [f for f in dead if cond(f)]
        w = l = d = 0
        for f in sub:
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
        wr = 100 * w / n if n else 0
        print(f"  {name:34s} n={len(sub):4d} WR={wr:5.2f}% net={w*PAYOUT-l:+7.1f}R")

    # ---- REV 0.90-0.93 sub-segments (can anything save it without filtering?) ----
    print("\n== REV 0.90-0.93 sub-segments (TRAIN, keep dir vs flip) ==")
    r9 = [f for f in TRAIN if f["v1_module"] == "REVERSAL" and 0.90 <= f["pos"] < 0.93]
    for name, cond in [
        ("range>=2.0", lambda f: f["range_atr"] >= 2.0),
        ("range 1.5-2.0", lambda f: 1.5 <= f["range_atr"] < 2.0),
        ("range<1.5", lambda f: f["range_atr"] < 1.5),
        ("|gap|>=0.2", lambda f: abs(f["ema_gap_atr"]) >= 0.2),
        ("|gap|<0.2", lambda f: abs(f["ema_gap_atr"]) < 0.2),
    ]:
        sub = [f for f in r9 if cond(f)]
        w = sum(1 for f in sub if f["v1_result"] == "WIN")
        l = sum(1 for f in sub if f["v1_result"] == "LOSS")
        print(f"  {name:16s} n={len(sub):4d} keep={w*PAYOUT-l:+7.1f}R flip={l*PAYOUT-w:+7.1f}R")


if __name__ == "__main__":
    main()

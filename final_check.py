#!/usr/bin/env python3
"""Final validation of v2 survivors: 3-way split (Jul/Aug/Sep) + bucket details."""
import sys
sys.path.insert(0, ".")
from sweep_features import enrich
from analyze_losers import load, replay

PAYOUT = 0.8
HSET = (8, 12, 15, 16, 18)


def month(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def apply(rows, hour_flip=True, ema_flip=True):
    net, flips = 0.0, {"hour": 0, "ema": 0}
    for f in rows:
        d = f["v1_signal"]
        if f["v1_module"] == "MOMENTUM":
            if hour_flip and f.get("hour") in HSET:
                d = "PUT" if d == "CALL" else "CALL"
                flips["hour"] += 1
            elif ema_flip and f.get("ema50") is not None and (
                    (f["v1_signal"] == "CALL") != (f["close_k"] > f["ema50"])):
                d = "PUT" if d == "CALL" else "CALL"
                flips["ema"] += 1
        ep, en = f["expiry_price"], f["entry_price"]
        if (ep > en if d == "CALL" else ep < en):
            net += PAYOUT
        elif ep != en:
            net -= 1.0
    return net, flips


def main():
    rows = load()
    by_ts = {c["ts"]: c for c in rows}
    feats = enrich(rows, replay(rows))
    sig = [f for f in feats if f["v1_signal"] and f.get("ema9") is not None
           and f["expiry_price"] is not None]
    for f in sig:
        f["close_k"] = by_ts[f["entry_ts"] - 60]["close"] if (f["entry_ts"] - 60) in by_ts else None
        # note: k = rows[i-1]; entry-60 may miss on gaps; fallback:
        if f["close_k"] is None:
            f["close_k"] = rows[f["i"] - 1]["close"]
    # EMA50 availability check (warmup fallback keeps count: no flip if None)
    noema = sum(1 for f in sig if f.get("ema50") is None)
    print(f"total signals={len(sig)} without-EMA50={noema} (fallback keeps v1 dir, count preserved)")

    print("\n== 3-WAY: base vs +hourflip vs +ema50 vs +joint (net R) ==")
    print(f"  {'split':8s} {'n':>5s} {'base':>8s} {'+hour':>8s} {'+ema50':>8s} {'+joint':>8s}")
    for name, sub in (("TRAIN", [f for f in sig if f["split"] == "TRAIN"]),
                      ("HOLDOUT", [f for f in sig if f["split"] == "HOLDOUT"]),
                      ("Jul", [f for f in sig if month(f["entry_ts"]) == "2026-07"]),
                      ("Aug", [f for f in sig if month(f["entry_ts"]) == "2026-08"]),
                      ("Sep", [f for f in sig if month(f["entry_ts"]) == "2026-09"]),
                      ("FULL", sig)):
        b, _ = apply(sub, False, False)
        h, fh = apply(sub, True, False)
        e, fe = apply(sub, False, True)
        j, fj = apply(sub, True, True)
        print(f"  {name:8s} {len(sub):5d} {b:+8.1f} {h:+8.1f} {e:+8.1f} {j:+8.1f}   flipsH={fh['hour']} flipsE={fe['ema']}")

    print("\n== flipped-hour details: MOM WR TRAIN vs HOLDOUT (v1 dir) ==")
    for hh in sorted(HSET):
        for sname, sub in (("TRAIN", [f for f in sig if f["split"] == "TRAIN"]),
                            ("HOLD", [f for f in sig if f["split"] == "HOLDOUT"])):
            rws = [f for f in sub if f["v1_module"] == "MOMENTUM" and f.get("hour") == hh]
            w = sum(1 for f in rws if f["v1_result"] == "WIN")
            l = sum(1 for f in rws if f["v1_result"] == "LOSS")
            n = w + l
            print(f"  h={hh:2d} {sname:5s}: n={len(rws):3d} WR={100*w/n if n else 0:5.2f}% old={w*PAYOUT-l:+6.1f}R flip={l*PAYOUT-w:+6.1f}R")

    print("\n== EMA50-conflict bucket details (MOM only, v1 dir) ==")
    for sname, sub in (("TRAIN", [f for f in sig if f["split"] == "TRAIN"]),
                        ("HOLD", [f for f in sig if f["split"] == "HOLDOUT"])):
        rws = [f for f in sub if f["v1_module"] == "MOMENTUM" and f.get("ema50") is not None
               and ((f["v1_signal"] == "CALL") != (f["close_k"] > f["ema50"]))]
        w = sum(1 for f in rws if f["v1_result"] == "WIN")
        l = sum(1 for f in rws if f["v1_result"] == "LOSS")
        n = w + l
        print(f"  {sname:5s}: n={len(rws):4d} WR={100*w/n if n else 0:5.2f}% old={w*PAYOUT-l:+7.1f}R flip={l*PAYOUT-w:+7.1f}R")

    print("\n== dz pos<0.60 trend ADD: 3-way ==")
    dead = [f for f in feats if (f["v1_signal"] is None and f.get("ema9") is not None
                                 and f["expiry_price"] is not None
                                 and f["v1_reason"] == "CLOSE_POSITION_OUT_OF_ZONE"
                                 and f.get("pos") is not None and f["pos"] < 0.60)]
    for name, sub in (("TRAIN", [f for f in dead if f["split"] == "TRAIN"]),
                      ("HOLD", [f for f in dead if f["split"] == "HOLDOUT"]),
                      ("Jul", [f for f in dead if month(f["entry_ts"]) == "2026-07"]),
                      ("Aug", [f for f in dead if month(f["entry_ts"]) == "2026-08"]),
                      ("Sep", [f for f in dead if month(f["entry_ts"]) == "2026-09"])):
        w = l = d = 0
        for f in sub:
            take_call = (f["dir"] == "BULLISH")
            ep, en = f["expiry_price"], f["entry_price"]
            if (ep > en if take_call else ep < en):
                w += 1
            elif ep == en:
                d += 1
            else:
                l += 1
        n = w + l
        print(f"  {name:5s}: n={len(sub):3d} WR={100*w/n if n else 0:5.2f}% net={w*PAYOUT-l:+6.1f}R")


if __name__ == "__main__":
    main()

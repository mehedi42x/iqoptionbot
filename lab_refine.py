#!/usr/bin/env python3
"""Round 3: rescue the pos 0.8-0.9 slice + middle thresholds + session splits."""
import sys
sys.path.insert(0, ".")
from lab_momentum import load, features, HOLDOUT_START, WARM
from datetime import datetime, timezone

PAYOUT = 0.85
SKIP = {3, 20, 21, 22}


def FD(f):
    return "PUT" if f["bull"] else ("CALL" if f["bear"] else None)


def keep_atr(f):
    return f.get("atr") and f["atr"] > 0


def main():
    rows = load()
    F = features(rows)
    n = len(rows)
    RULES = [
        ("G0 slice 0.8-0.9", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 else None),
        ("G1 +range>=1.2", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and keep_atr(f) and f["range_atr"] >= 1.2 else None),
        ("G2 +range>=1.5", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and keep_atr(f) and f["range_atr"] >= 1.5 else None),
        ("G3 +body>=0.5", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and f["body_ratio"] >= 0.5 else None),
        ("G4 r1.2+b.5", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and keep_atr(f) and f["range_atr"] >= 1.2 and f["body_ratio"] >= 0.5 else None),
        ("G5 +breakout20", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and f.get("hh20") is not None and (rows and False) else None),
        ("G6 ex-skip-hours", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and f["hour"] not in SKIP else None),
        ("G7 skip-hours only", lambda f: FD(f) if 0.8 <= f["pos_col"] < 0.9 and f["hour"] in SKIP else None),
        ("G8 pos>=0.85", lambda f: FD(f) if f["pos_col"] >= 0.85 else None),
        ("G9 pos.85+r1.0", lambda f: FD(f) if f["pos_col"] >= 0.85 and keep_atr(f) and f["range_atr"] >= 1.0 else None),
        ("G10 F6c ex-skip", lambda f: FD(f) if f["pos_col"] >= 0.9 and f["hour"] not in SKIP else None),
        ("G11 F6c skip-only", lambda f: FD(f) if f["pos_col"] >= 0.9 and f["hour"] in SKIP else None),
        ("G12 F6c+range>=0.5", lambda f: FD(f) if f["pos_col"] >= 0.9 and keep_atr(f) and f["range_atr"] >= 0.5 else None),
        ("G13 F6b+range>=0.5", lambda f: FD(f) if f["pos_col"] >= 0.8 and keep_atr(f) and f["range_atr"] >= 0.5 else None),
        ("G14 F6c+body>=0.3", lambda f: FD(f) if f["pos_col"] >= 0.9 and f["body_ratio"] >= 0.3 else None),
    ]
    print("payout=85% breakeven=54.05%")
    print(f"\n{'rule':22s} {'TRAIN n':>8s} {'WR':>6s} {'net$':>9s} | {'HO n':>6s} {'WR':>6s} {'net$':>8s} | {'Jul$':>8s} {'Aug$':>8s} {'Sep$':>8s}")
    for name, fn in RULES:
        buckets = {"TR": [0, 0, 0], "HO": [0, 0, 0], "J": [0, 0, 0], "A": [0, 0, 0], "S": [0, 0, 0]}
        for i in range(WARM, n - 1):
            f = F[i]
            try:
                d = fn(f)
            except (KeyError, TypeError):
                d = None
            if d is None:
                continue
            en = rows[i]["open"]
            ep = rows[i + 1]["open"]
            r = 0 if (ep > en if d == "CALL" else ep < en) else (2 if ep == en else 1)
            ts = rows[i]["ts"]
            buckets["HO" if ts >= HOLDOUT_START else "TR"][r] += 1
            m = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
            buckets[{"2026-07": "J", "2026-08": "A", "2026-09": "S"}[m]][r] += 1
        row = {}
        for k in ("TR", "HO", "J", "A", "S"):
            w, l, dr = buckets[k][0], buckets[k][1], buckets[k][2]
            nn = w + l
            row[k] = (w + l + dr, 100 * w / nn if nn else 0, w * PAYOUT - l)
        t, h = row["TR"], row["HO"]
        ok = "✅" if t[2] > 0 and h[2] > 0 else "  "
        print(f"{ok}{name:20s} {t[0]:8d} {t[1]:5.2f}% {t[2]:+9.1f} | {h[0]:6d} {h[1]:5.2f}% {h[2]:+8.1f} | {row['J'][2]:+8.1f} {row['A'][2]:+8.1f} {row['S'][2]:+8.1f}")


if __name__ == "__main__":
    main()

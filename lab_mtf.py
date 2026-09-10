#!/usr/bin/env python3
"""MTF Round 1: 30s signals (+1m context) vs MS2-on-window baseline.
Window: Aug 20-Sep 10 (30s coverage). TRAIN=Aug20-31, HO=Sep1-10.
Expiry 60s, payout .85, MAX_CONCURRENT=1 (busy_until) replicated."""
import sys, csv
sys.path.insert(0, ".")
from datetime import datetime, timezone

P = 0.85
HO_START = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
WIN_START = datetime(2026, 8, 20, tzinfo=timezone.utc).timestamp()
SKIP = {3, 20, 21, 22}
WEAK = {8, 9, 10, 11, 13, 14}


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({"ts": float(r["timestamp"]), "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
    rows.sort(key=lambda c: c["ts"])
    return rows[:-1]  # drop forming tail


C30 = load("candles_asset_1861_30s_30d.csv")
M1 = load("candles_asset_1861_60s_30d.csv")
M1X = {r["ts"]: j for j, r in enumerate(M1)}
S30X = {r["ts"]: i for i, r in enumerate(C30)}


def m1_feats():
    n = len(M1)
    cl = [r["close"] for r in M1]
    rg = [r["high"] - r["low"] for r in M1]
    F = []
    for j, r in enumerate(M1):
        d = {"pos": None, "bull": None, "doji": r["close"] == r["open"], "flat": rg[j] <= 0,
             "hour": datetime.fromtimestamp(r["ts"], tz=timezone.utc).hour,
             "vr": None, "calm": False, "trend": None, "atr": None}
        if not d["flat"] and not d["doji"]:
            b = r["close"] > r["open"]
            d["bull"] = b
            d["pos"] = (r["close"] - r["low"]) / rg[j] if b else (r["high"] - r["close"]) / rg[j]
        if j >= 60:
            r5 = sum(rg[j - 4:j + 1]) / 5
            r60 = sum(rg[j - 59:j + 1]) / 60
            d["atr"] = r60
            if r60 > 0:
                d["vr"] = r5 / r60
                d["calm"] = d["vr"] < 0.864
        if j >= 50:
            s50 = sum(cl[j - 49:j + 1]) / 50
            s20 = sum(cl[j - 19:j + 1]) / 20
            c = cl[j]
            d["trend"] = 1 if (c > s50 and s20 > s50) else (-1 if (c < s50 and s20 < s50) else 0)
        F.append(d)
    return F


MF = m1_feats()


def ctx1m(t):
    """last CLOSED 1m bar index as of 30s-time t (entry open)."""
    o = (t - 60) // 60 * 60
    return M1X.get(float(o))


def res30(i_entry, d):
    """60s expiry from 30s entry index (mimics backtest fallback)."""
    t = C30[i_entry]["ts"]
    en = C30[i_entry]["open"]
    j = S30X.get(t + 60)
    if j is not None:
        ep = C30[j]["open"]
    else:
        ep = None
        for k in range(len(C30) - 1, -1, -1):
            if C30[k]["ts"] <= t + 60:
                if k <= i_entry:
                    return None
                ep = C30[k]["close"]
                break
        if ep is None:
            return None
    return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")


def res1m(j_entry, d):
    t = M1[j_entry]["ts"]
    en = M1[j_entry]["open"]
    j = M1X.get(t + 60)
    if j is not None:
        ep = M1[j]["open"]
    else:
        return None
    return "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")


def block(ts):
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    if d < datetime(2026, 8, 27, tzinfo=timezone.utc):
        return "B1"
    if d < datetime(2026, 9, 4, tzinfo=timezone.utc):
        return "B2"
    return "B3"


def show(name, sigs):
    """sigs: list of (entry_ts, result). Applies busy_until."""
    sigs = sorted(sigs)
    bk = {"TR": [0, 0, 0], "HO": [0, 0, 0], "B1": [0, 0], "B2": [0, 0], "B3": [0, 0]}
    busy, skipped = None, 0
    for t, r in sigs:
        if busy is not None and t < busy:
            skipped += 1
            continue
        busy = t + 60
        sp = "HO" if t >= HO_START else "TR"
        bk[sp][0 if r == "WIN" else (2 if r == "DRAW" else 1)] += 1
        b = block(t)
        if r == "WIN":
            bk[b][0] += 1
        elif r == "LOSS":
            bk[b][1] += 1
    o = {}
    for k in ("TR", "HO"):
        w, l, dr = bk[k]
        o[k] = (w + l + dr, 100 * w / (w + l) if (w + l) else 0, w * P - l)
    t, h = o["TR"], o["HO"]
    b = {k: bk[k][0] * P - bk[k][1] for k in ("B1", "B2", "B3")}
    ok = "✅" if (t[2] > 0 and h[2] > 0) else "  "
    print(f"{ok} {name:34s} | TR n={t[0]:5d} {t[1]:5.2f}% {t[2]:+8.1f} | HO n={h[0]:5d} {h[1]:5.2f}% {h[2]:+8.1f} | B1{b['B1']:+7.1f} B2{b['B2']:+7.1f} B3{b['B3']:+7.1f} | sk={skipped}")
    return o


def ms2_1m(j):
    """MS2 rules on 1m signal-bar j -> direction or None."""
    f = MF[j]
    r = M1[j]
    if f["flat"] or f["doji"]:
        return None
    h = f["hour"]
    if h in WEAK:
        return None
    skip = h in SKIP
    monster = (not skip) and h in (19, 23)
    calm_mid = (not skip) and f["calm"] and f["pos"] >= 0.85 and f["pos"] < 0.90
    if h in (12, 15) and not calm_mid:
        return None
    if skip:
        thr = 0.75 if (f["calm"] and h in (20, 21, 22)) else 0.80
    else:
        thr = 0.90 if monster else 0.93
    d = "PUT" if f["bull"] else "CALL"
    if f["pos"] >= thr:
        return d
    if calm_mid:
        return d
    return None


def main():
    print(f"30s: {len(C30)} ({datetime.fromtimestamp(C30[0]['ts'],tz=timezone.utc):%m-%d} -> {datetime.fromtimestamp(C30[-1]['ts'],tz=timezone.utc):%m-%d %H:%M})")
    print(f"1m : {len(M1)} ({datetime.fromtimestamp(M1[0]['ts'],tz=timezone.utc):%m-%d} -> {datetime.fromtimestamp(M1[-1]['ts'],tz=timezone.utc):%m-%d %H:%M})")

    # BASELINE: MS2 on window (1m)
    sigs = []
    for j in range(1, len(M1)):
        if M1[j]["ts"] < WIN_START:
            continue
        d = ms2_1m(j - 1)
        if d is None:
            continue
        r = res1m(j, d)
        if r is None:
            continue
        sigs.append((M1[j]["ts"], r))
    print("\n== BASELINE MS2-on-window (1m) ==")
    show("MS2 window", sigs)

    # 30s features per signal-bar (bar i-1, entry at bar i open)
    print("\n== A: plain 30s fade (non-weak) ==")
    for thr, nm in ((0.85, "A1 30s>=.85"), (0.90, "A2 30s>=.90"), (0.93, "A3 30s>=.93"), (0.95, "A4 30s>=.95")):
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            k = C30[i - 1]
            rg = k["high"] - k["low"]
            if rg <= 0 or k["close"] == k["open"]:
                continue
            hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
            if hr in WEAK:
                continue
            b = k["close"] > k["open"]
            pos = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
            if pos < thr:
                continue
            r = res30(i, "PUT" if b else "CALL")
            if r is None:
                continue
            sigs.append((t, r))
        show(nm, sigs)
    # A-weak
    sigs = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t < WIN_START:
            continue
        k = C30[i - 1]
        rg = k["high"] - k["low"]
        if rg <= 0 or k["close"] == k["open"]:
            continue
        hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
        if hr not in WEAK:
            continue
        b = k["close"] > k["open"]
        pos = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
        if pos < 0.93:
            continue
        r = res30(i, "PUT" if b else "CALL")
        if r is None:
            continue
        sigs.append((t, r))
    show("A0 30s>=.93 WEAK-only", sigs)

    print("\n== E: 30s sniper h21/22 ==")
    for lim, nm in ((0.5, "E1a h21/22 r/a<.5"), (1.0, "E1b h21/22 r/a<1")):
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
            if hr not in (21, 22):
                continue
            k = C30[i - 1]
            rg = k["high"] - k["low"]
            if rg <= 0 or k["close"] == k["open"]:
                continue
            j = ctx1m(t)
            if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
                continue
            if rg / MF[j]["atr"] >= lim:
                continue
            b = k["close"] > k["open"]
            pos = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
            if pos < 0.80:
                continue
            r = res30(i, "PUT" if b else "CALL")
            if r is None:
                continue
            sigs.append((t, r))
        show(nm, sigs)

    print("\n== F: 30s>=.93 x 1m-trend ==")
    for nm, cond in (("F-with", lambda f, d: (f == 1 and d == "CALL") or (f == -1 and d == "PUT")),
                     ("F-vs", lambda f, d: (f == 1 and d == "PUT") or (f == -1 and d == "CALL")),
                     ("F-flat", lambda f, d: f == 0)):
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
            if hr in WEAK:
                continue
            k = C30[i - 1]
            rg = k["high"] - k["low"]
            if rg <= 0 or k["close"] == k["open"]:
                continue
            b = k["close"] > k["open"]
            pos = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
            if pos < 0.93:
                continue
            j = ctx1m(t)
            if j is None or MF[j]["trend"] is None:
                continue
            dd = "PUT" if b else "CALL"
            if not cond(MF[j]["trend"], dd):
                continue
            r = res30(i, dd)
            if r is None:
                continue
            sigs.append((t, r))
        show(nm, sigs)

    print("\n== B/G/D2: confluence / freshness / delayed-entry ==")
    # B1/B2: 30s fade + 1m same-side extreme
    for thr30, thr1m, nm in ((0.90, 0.80, "B1 30s.90+1m.80"), (0.85, 0.90, "B2 30s.85+1m.90")):
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
            if hr in WEAK:
                continue
            k = C30[i - 1]
            rg = k["high"] - k["low"]
            if rg <= 0 or k["close"] == k["open"]:
                continue
            b = k["close"] > k["open"]
            pos = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
            if pos < thr30:
                continue
            j = ctx1m(t)
            if j is None:
                continue
            f = MF[j]
            if f["flat"] or f["doji"] or f["pos"] is None or f["pos"] < thr1m:
                continue
            dd = "PUT" if b else "CALL"
            if ("PUT" if f["bull"] else "CALL") != dd:
                continue
            r = res30(i, dd)
            if r is None:
                continue
            sigs.append((t, r))
        show(nm, sigs)
    # G1: 1m-mid + fresh second-half
    sigs = []
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        if t < WIN_START:
            continue
        f = MF[j - 1]
        if f["flat"] or f["doji"]:
            continue
        h = f["hour"]
        if h in WEAK or h in SKIP:
            continue
        if not (0.85 <= f["pos"] < 0.93):
            continue
        dd = "PUT" if f["bull"] else "CALL"
        # second 30s half of signal minute
        i2 = S30X.get(M1[j - 1]["ts"] + 30)
        if i2 is None:
            continue
        k = C30[i2]
        rg = k["high"] - k["low"]
        if rg <= 0 or k["close"] == k["open"]:
            continue
        b = k["close"] > k["open"]
        p2 = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
        if p2 < 0.90 or ("PUT" if b else "CALL") != dd:
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        sigs.append((t, r))
    show("G1 1m-mid+fresh30s", sigs)
    # D2: MS2 signals, entry delayed +30s (expiry +90s)
    sigs = []
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        if t < WIN_START:
            continue
        d = ms2_1m(j - 1)
        if d is None:
            continue
        ie = S30X.get(t + 30)
        if ie is None:
            continue
        en = C30[ie]["open"]
        ix = S30X.get(t + 90)
        if ix is not None:
            ep = C30[ix]["open"]
        else:
            ep = None
            for kk in range(len(C30) - 1, -1, -1):
                if C30[kk]["ts"] <= t + 90:
                    if kk <= ie:
                        break
                    ep = C30[kk]["close"]
                    break
            if ep is None:
                continue
        r = "WIN" if (ep > en if d == "CALL" else ep < en) else ("DRAW" if ep == en else "LOSS")
        sigs.append((t + 30, r))
    show("D2 MS2 delayed+30s", sigs)


if __name__ == "__main__":
    main()

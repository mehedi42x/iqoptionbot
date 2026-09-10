#!/usr/bin/env python3
"""MTF Round 2: 30s hour-tuning + full 30s-MS2-port + sniper+ + unions + G1-marginal.
PASS-VOLUME: n>MS2base & WR>MS2base & TR_up & HO_up. PASS-SNIPER: max HO-WR (n>=500, 3/3+)."""
import sys
sys.path.insert(0, ".")
from lab_mtf import (C30, M1, MF, M1X, S30X, ctx1m, res30, res1m, block, show,
                     ms2_1m, SKIP, WEAK, HO_START, WIN_START, P)
from datetime import datetime, timezone


def feats30(i):
    k = C30[i - 1]
    rg = k["high"] - k["low"]
    if rg <= 0 or k["close"] == k["open"]:
        return None
    b = k["close"] > k["open"]
    pos = (k["close"] - k["low"]) / rg if b else (k["high"] - k["close"]) / rg
    return {"rg": rg, "pos": pos, "dir": "PUT" if b else "CALL"}


def base_ms2():
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
    return sigs


def main():
    B = show("BASE MS2-window", base_ms2())

    print("\n== T: 30s hour-tier tuning ==")
    T = [
        ("T1 30s.80 skip", lambda hr: hr in SKIP, 0.80),
        ("T2 30s.85 skip", lambda hr: hr in SKIP, 0.85),
        ("T3 30s.90 monster", lambda hr: hr in (19, 23), 0.90),
        ("T4 30s.93 normal", lambda hr: hr not in SKIP and hr not in WEAK and hr not in (12, 15), 0.93),
        ("T5 30s.93 h12/15", lambda hr: hr in (12, 15), 0.93),
        ("T6 30s.90 normal", lambda hr: hr not in SKIP and hr not in WEAK, 0.90),
    ]
    for nm, hcond, thr in T:
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
            if not hcond(hr):
                continue
            f = feats30(i)
            if f is None or f["pos"] < thr:
                continue
            r = res30(i, f["dir"])
            if r is None:
                continue
            sigs.append((t, r))
        show(nm, sigs)

    print("\n== H: 30s-MS2-port systems ==")
    def port(with_h1215_trim, with_calm_mid, trend_filter):
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
            if hr in WEAK:
                continue
            f = feats30(i)
            if f is None:
                continue
            j = ctx1m(t)
            calm = MF[j]["calm"] if j is not None else False
            skip = hr in SKIP
            monster = (not skip) and hr in (19, 23)
            calm_mid = (not skip) and calm and 0.85 <= f["pos"] < 0.90
            if with_h1215_trim and hr in (12, 15) and not (with_calm_mid and calm_mid):
                continue
            if skip:
                thr = 0.75 if (calm and hr in (20, 21, 22)) else 0.80
            else:
                thr = 0.90 if monster else 0.93
            dd = None
            if f["pos"] >= thr:
                dd = f["dir"]
            elif with_calm_mid and calm_mid:
                dd = f["dir"]
            if dd is None:
                continue
            if trend_filter and j is not None:
                tr = MF[j]["trend"]
                withT = (tr == 1 and dd == "CALL") or (tr == -1 and dd == "PUT")
                vsT = (tr == 1 and dd == "PUT") or (tr == -1 and dd == "CALL")
                if trend_filter == "vs" and not vsT:
                    continue
                if trend_filter == "novs" and vsT:
                    continue
                if trend_filter == "nowith" and withT:
                    continue
            r = res30(i, dd)
            if r is None:
                continue
            sigs.append((t, r))
        return sigs

    show("H1 port-full", port(True, True, None))
    show("H1b no-h1215-trim", port(False, True, None))
    show("H1c no-calm-mid", port(True, False, None))
    show("H2 vs-only", port(True, True, "vs"))
    show("H2b no-withT", port(True, True, "nowith"))

    print("\n== S30: sniper+ ==")
    def e1b(i, t, extra=None):
        hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
        if hr not in (21, 22):
            return None
        f = feats30(i)
        if f is None or f["pos"] < 0.80:
            return None
        j = ctx1m(t)
        if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
            return None
        if f["rg"] / MF[j]["atr"] >= 1.0:
            return None
        if extra == "vs":
            tr = MF[j]["trend"]
            if not ((tr == 1 and f["dir"] == "PUT") or (tr == -1 and f["dir"] == "CALL")):
                return None
        if extra == "conf":
            g = MF[j]
            if g["flat"] or g["doji"] or g["pos"] is None or g["pos"] < 0.80:
                return None
            if ("PUT" if g["bull"] else "CALL") != f["dir"]:
                return None
        if extra == "calm" and not MF[j]["calm"]:
            return None
        return f["dir"]

    for nm, ex in (("S30a E1b+vsT", "vs"), ("S30b E1b+conf", "conf"), ("S30c E1b+calm", "calm"),
                   ("S30d E1b plain", None)):
        sigs = []
        for i in range(1, len(C30)):
            t = C30[i]["ts"]
            if t < WIN_START:
                continue
            dd = e1b(i, t, ex)
            if dd is None:
                continue
            r = res30(i, dd)
            if r is None:
                continue
            sigs.append((t, r))
        show(nm, sigs)

    print("\n== U: unions (busy_until) + G1-marginal ==")
    m = base_ms2()
    mset = {t for t, _ in m}
    # U1: MS2 + B2-30s
    extra = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t < WIN_START or t in mset:
            continue
        hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
        if hr in WEAK:
            continue
        f = feats30(i)
        if f is None or f["pos"] < 0.85:
            continue
        j = ctx1m(t)
        if j is None:
            continue
        g = MF[j]
        if g["flat"] or g["doji"] or g["pos"] is None or g["pos"] < 0.90:
            continue
        if ("PUT" if g["bull"] else "CALL") != f["dir"]:
            continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        extra.append((t, r))
    show("U1 MS2+B2", m + extra)
    # U2: MS2 + A3-30s
    extra = []
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t < WIN_START or t in mset:
            continue
        hr = datetime.fromtimestamp(t, tz=timezone.utc).hour
        if hr in WEAK:
            continue
        f = feats30(i)
        if f is None or f["pos"] < 0.93:
            continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        extra.append((t, r))
    show("U2 MS2+A3", m + extra)
    # G1 marginal (exclude MS2-overlap entries)
    sigs = []
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        if t < WIN_START or t in mset:
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
    o = show("G1m marginal", sigs)
    show("MS2+G1m", m + sigs)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Comb operation P1: regenerate U4 exactly, verify vs backtest CSV, slice losers.
TRAIN=Aug11-31, HO=Sep1-10. Bars for cuts: TR-net<0 AND HO-net<0 (both splits)."""
import sys, csv
sys.path.insert(0, ".")
from lab_mtf import (C30, M1, MF, M1X, S30X, ctx1m, res30, res1m, ms2_1m,
                     SKIP, WEAK, HO_START)
from lab_mtf2 import feats30
from datetime import datetime, timezone
from collections import defaultdict

P = 0.85
B1_END = datetime(2026, 8, 27, tzinfo=timezone.utc).timestamp()
B2_END = datetime(2026, 9, 4, tzinfo=timezone.utc).timestamp()

VOL30, VOL1M = {}, {}
for p, d in (("candles_asset_1861_30s_30d.csv", VOL30), ("candles_asset_1861_60s_30d.csv", VOL1M)):
    for r in csv.DictReader(open(p)):
        d[float(r["timestamp"])] = float(r["volume"])

ATRS = sorted(a for f in MF for a in (f["atr"],) if a)
A_LO, A_HI = ATRS[len(ATRS) // 3], ATRS[2 * len(ATRS) // 3]
V1 = sorted(VOL1M.values()); V1_LO, V1_HI = V1[len(V1) // 3], V1[2 * len(V1) // 3]
V30 = sorted(VOL30.values()); V3_LO, V3_HI = V30[len(V30) // 3], V30[2 * len(V30) // 3]


def hmorph(o, h, l, c):
    rg = h - l
    if rg <= 0 or c == o:
        return None
    b = c > o
    pos = (c - l) / rg if b else (h - c) / rg
    body = abs(c - o) / rg
    upw = (h - max(c, o)) / rg
    return {"pos": pos, "bull": b, "body": body, "upw": upw, "rng": rg,
            "dir": "PUT" if b else "CALL"}


def runup_1m(j_sig):
    n, k = 0, j_sig - 1
    sb = M1[j_sig]["close"] > M1[j_sig]["open"]
    while k >= 0 and n < 9:
        r = M1[k]
        if r["close"] == r["open"] or (r["close"] > r["open"]) != sb:
            break
        n += 1
        k -= 1
    return n


def runup_30(i_sig):
    n, k = 0, i_sig - 1
    sb = C30[i_sig]["close"] > C30[i_sig]["open"]
    while k >= 0 and n < 9:
        r = C30[k]
        if r["close"] == r["open"] or (r["close"] > r["open"]) != sb:
            break
        n += 1
        k -= 1
    return n


def ms2_mod(j):
    f, h = MF[j], MF[j]["hour"]
    skip = h in SKIP
    monster = (not skip) and h in (19, 23)
    calm_mid = (not skip) and f["calm"] and f["pos"] >= 0.85 and f["pos"] < 0.90
    if skip:
        sc = f["calm"] and h in (20, 21, 22)
        return "FADE_SKIP_CALM" if (sc and f["pos"] < 0.80) else "FADE_SKIP"
    if f["pos"] >= (0.90 if monster else 0.93):
        return "FADE_MONSTER" if (monster and f["pos"] < 0.93) else "FADE"
    return "FADE_CALM_MID"


def dt(t):
    return datetime.fromtimestamp(t, tz=timezone.utc)


def regen():
    raw = []
    mset = set()
    for j in range(1, len(M1)):
        d = ms2_1m(j - 1)
        if d is None:
            continue
        t = M1[j]["ts"]
        mset.add(t)  # SIGNAL-ts (incl. res-None Friday-edge ghosts that tie-block 30s legs live)
        r = res1m(j, d)
        if r is None:
            continue
        s, f = M1[j - 1], MF[j - 1]
        m = hmorph(s["open"], s["high"], s["low"], s["close"])
        tr = f["trend"]
        raw.append({"t": t, "r": r, "leg": ms2_mod(j - 1), "tf": 60, "dir": d,
                    "eh": dt(t).hour, "em": dt(t).minute, "wd": dt(t).strftime("%a"),
                    "sh": f["hour"], "pos": m["pos"], "bull": m["bull"], "body": m["body"],
                    "upw": m["upw"], "rng": m["rng"], "calm": f["calm"], "vr": f["vr"],
                    "trend": tr, "tmode": "flat" if tr == 0 else (
                        "vs" if (tr == 1 and d == "PUT") or (tr == -1 and d == "CALL") else "with"),
                    "atr": f["atr"], "size": (m["rng"] / f["atr"] if f["atr"] else None),
                    "run": runup_1m(j - 1), "gap": (t - M1[j - 1]["ts"]) != 60,
                    "cont": M1X.get(t + 60, -1) == j + 1,
                    "vol": VOL1M.get(s["ts"]), "s30": None, "ctx": None, "fresh": None})
    for i in range(1, len(C30)):
        t = C30[i]["ts"]
        if t in mset:
            continue
        if dt(t).hour not in (21, 22):
            continue
        f = feats30(i)
        if f is None or f["pos"] < 0.80:
            continue
        j = ctx1m(t)
        if j is None or MF[j]["atr"] is None or MF[j]["atr"] <= 0:
            continue
        if f["rg"] / MF[j]["atr"] >= 1.0:
            continue
        r = res30(i, f["dir"])
        if r is None:
            continue
        k = C30[i - 1]
        m = hmorph(k["open"], k["high"], k["low"], k["close"])
        g = MF[j]
        tr = g["trend"]
        raw.append({"t": t, "r": r, "leg": "E1B_30S", "tf": 30, "dir": f["dir"],
                    "eh": dt(t).hour, "em": dt(t).minute, "wd": dt(t).strftime("%a"),
                    "sh": dt(k["ts"]).hour, "pos": m["pos"], "bull": m["bull"], "body": m["body"],
                    "upw": m["upw"], "rng": m["rng"], "calm": g["calm"], "vr": g["vr"],
                    "trend": tr, "tmode": "flat" if tr == 0 else (
                        "vs" if (tr == 1 and f["dir"] == "PUT") or (tr == -1 and f["dir"] == "CALL") else "with"),
                    "atr": g["atr"], "size": f["rg"] / g["atr"],
                    "run": runup_30(i - 1), "gap": (t - C30[i - 1]["ts"]) != 30,
                    "cont": S30X.get(t + 60, -1) == i + 2,
                    "vol": VOL30.get(k["ts"]), "s30": None,
                    "ctx": {"pos": g["pos"], "bull": g["bull"]}, "fresh": None})
    for j in range(1, len(M1)):
        t = M1[j]["ts"]
        if t in mset:
            continue
        f = MF[j - 1]
        if f["flat"] or f["doji"]:
            continue
        if f["hour"] in WEAK or f["hour"] in SKIP:
            continue
        if not (0.85 <= f["pos"] < 0.93):
            continue
        dd = "PUT" if f["bull"] else "CALL"
        i2 = S30X.get(M1[j - 1]["ts"] + 30)
        if i2 is None:
            continue
        k = C30[i2]
        m2 = hmorph(k["open"], k["high"], k["low"], k["close"])
        if m2 is None or m2["pos"] < 0.90 or m2["dir"] != dd:
            continue
        r = res1m(j, dd)
        if r is None:
            continue
        s = M1[j - 1]
        m = hmorph(s["open"], s["high"], s["low"], s["close"])
        tr = f["trend"]
        raw.append({"t": t, "r": r, "leg": "G1M_FRESH30", "tf": 60, "dir": dd,
                    "eh": dt(t).hour, "em": dt(t).minute, "wd": dt(t).strftime("%a"),
                    "sh": f["hour"], "pos": m["pos"], "bull": m["bull"], "body": m["body"],
                    "upw": m["upw"], "rng": m["rng"], "calm": f["calm"], "vr": f["vr"],
                    "trend": tr, "tmode": "flat" if tr == 0 else (
                        "vs" if (tr == 1 and dd == "PUT") or (tr == -1 and dd == "CALL") else "with"),
                    "atr": f["atr"], "size": (m["rng"] / f["atr"] if f["atr"] else None),
                    "run": runup_1m(j - 1), "gap": (t - M1[j - 1]["ts"]) != 60,
                    "cont": M1X.get(t + 60, -1) == j + 1,
                    "vol": VOL1M.get(s["ts"]), "s30": None, "ctx": None,
                    "fresh": {"pos": m2["pos"], "bull": m2["bull"], "body": m2["body"]}})
    raw.sort(key=lambda x: x["t"])
    busy, kept = None, []
    prev = None
    for x in raw:
        if busy is not None and x["t"] < busy:
            continue
        busy = x["t"] + 60
        x["prev"] = prev
        kept.append(x)
        prev = x["r"]
    return kept, raw


def net(rs):
    W = sum(1 for x in rs if x["r"] == "WIN")
    L = sum(1 for x in rs if x["r"] == "LOSS")
    return W, L, len(rs) - W - L, W * P - L


def show_slice(name, kept, keyfn, min_n=80):
    g = defaultdict(list)
    for x in kept:
        g[keyfn(x)].append(x)
    print(f"\n== {name} ==")
    for k in sorted(g, key=str):
        rs = g[k]
        if len(rs) < min_n:
            continue
        W, L, D, nn = net(rs)
        tr = [x for x in rs if x["t"] < HO_START]
        ho = [x for x in rs if x["t"] >= HO_START]
        Wt, Lt, Dt, nt = net(tr)
        Wh, Lh, Dh, nh = net(ho)
        wr = 100 * W / (W + L) if W + L else 0
        flag = "CUT?" if (nt < 0 and nh < 0) else ("mix" if (nt < 0) != (nh < 0) else "   ")
        print(f"{flag} {str(k):22s} | F n={len(rs):5d} {wr:5.2f}% {nn:+8.1f} | "
              f"TR n={len(tr):5d} {nt:+8.1f} | HO n={len(ho):4d} {nh:+7.1f} | L={L}")


def main():
    kept, raw = regen()
    W, L, D, nn = net(kept)
    print(f"LAB regen kept: n={len(kept)} W={W} L={L} D={D} WR={100*W/(W+L):.2f}% net={nn:+.1f}")
    rows = list(csv.DictReader(open("backtest_mtfv__trades_60s.csv")))
    Wb = sum(1 for r in rows if r["result"] == "WIN")
    Lb = sum(1 for r in rows if r["result"] == "LOSS")
    Db = len(rows) - Wb - Lb
    print(f"BACKTEST csv : n={len(rows)} W={Wb} L={Lb} D={Db} WR={100*Wb/(Wb+Lb):.2f}%")
    a = sorted(x["t"] for x in kept)
    b = sorted(float(r["entry_time"]) for r in rows)
    print("ENTRY-MATCH:", "EXACT" if a == b else f"DIFF lab={len(a)} bt={len(rows)}")
    ma = defaultdict(int)
    mb = defaultdict(int)
    for x in kept:
        ma[x["leg"]] += 1
    for r in rows:
        mb[r["module"]] += 1
    print("LEG-MATCH:", "EXACT" if ma == mb else f"{dict(ma)} vs {dict(mb)}")
    if a != b or ma != mb:
        return

    show_slice("S1 leg", kept, lambda x: x["leg"], 50)
    show_slice("S2 entry_hour", kept, lambda x: f"h{x['eh']:02d}", 50)
    show_slice("S3a pos-bucket ALL", kept, lambda x: (
        "p<.80" if x["pos"] < 0.80 else ("p.80-.85" if x["pos"] < 0.85 else (
            "p.85-.90" if x["pos"] < 0.90 else ("p.90-.93" if x["pos"] < 0.93 else (
                "p.93-.95" if x["pos"] < 0.95 else "p.95+"))))), 50)
    for leg in ("FADE", "FADE_SKIP", "FADE_CALM_MID", "E1B_30S"):
        sub = [x for x in kept if x["leg"] == leg]
        show_slice(f"S3b pos x {leg}", sub, lambda x: (
            "p<.85" if x["pos"] < 0.85 else ("p.85-.90" if x["pos"] < 0.90 else (
                "p.90-.93" if x["pos"] < 0.93 else ("p.93-.95" if x["pos"] < 0.95 else "p.95+")))), 40)
    show_slice("S4a size ALL", kept, lambda x: (
        "s<.5" if (x["size"] if x["size"] is not None else 9) < 0.5 else (
            "s.5-.75" if (x["size"] or 9) < 0.75 else (
            "s.75-1" if (x["size"] or 9) < 1.0 else ("s1-1.5" if (x["size"] or 9) < 1.5 else (
                "s1.5-2" if (x["size"] or 9) < 2.0 else "s2+"))))), 50)
    show_slice("S4b size x E1B", [x for x in kept if x["leg"] == "E1B_30S"], lambda x: (
        "s<.5" if x["size"] < 0.5 else ("s.5-.75" if x["size"] < 0.75 else "s.75-1")), 30)
    show_slice("S4c size x FADE", [x for x in kept if x["leg"] == "FADE"], lambda x: (
        "s<1" if (x["size"] or 9) < 1 else ("s1-1.5" if (x["size"] or 9) < 1.5 else (
            "s1.5-2" if (x["size"] or 9) < 2.0 else "s2+"))), 40)
    show_slice("S5 calm x leg", kept, lambda x: f"{x['leg']}:{'calm' if x['calm'] else 'norm'}", 40)
    show_slice("S6 tmode x leg", kept, lambda x: f"{x['leg']}:{x['tmode']}", 40)
    show_slice("S7 body", kept, lambda x: (
        "b<.3" if x["body"] < 0.3 else ("b.3-.5" if x["body"] < 0.5 else (
            "b.5-.7" if x["body"] < 0.7 else ("b.7-.9" if x["body"] < 0.9 else "b.9+")))), 50)
    show_slice("S8 upwick x dir", kept, lambda x: (
        f"{x['dir']}:u{'<.1' if x['upw'] < 0.1 else ('.1-.2' if x['upw'] < 0.2 else '.2+')}"), 50)
    show_slice("S9 dir x leg", kept, lambda x: f"{x['leg']}:{x['dir']}", 40)
    show_slice("S10 weekday", kept, lambda x: x["wd"], 50)
    show_slice("S11 gap_entry", kept, lambda x: f"gap{x['gap']}", 30)
    show_slice("S12 prev_result", kept, lambda x: f"prev{x['prev']}", 50)
    show_slice("S13 atr-level", kept, lambda x: (
        "aLow" if (x["atr"] if x["atr"] is not None else 0) < A_LO else (
            "aMid" if (x["atr"] or 0) < A_HI else "aHi")), 50)
    show_slice("S14a run1m x 1mlegs", [x for x in kept if x["tf"] == 60],
               lambda x: f"run{min(x['run'],3)}", 50)
    show_slice("S14b run30 x E1B", [x for x in kept if x["leg"] == "E1B_30S"],
               lambda x: f"run{min(x['run'],3)}", 30)
    show_slice("S15 E1B ctx-pos", [x for x in kept if x["leg"] == "E1B_30S"],
               lambda x: f"ctx{( 'lo' if (x['ctx']['pos'] if x['ctx']['pos'] is not None else 0)<0.7 else ('mid' if (x['ctx']['pos'] or 0)<0.85 else 'hi'))}", 30)
    show_slice("S16a G1M fresh-pos", [x for x in kept if x["leg"] == "G1M_FRESH30"],
               lambda x: f"fr{('<.93' if x['fresh']['pos']<0.93 else ('.93-.95' if x['fresh']['pos']<0.95 else '.95+'))}", 20)
    show_slice("S16b G1M 1m-pos", [x for x in kept if x["leg"] == "G1M_FRESH30"],
               lambda x: f"m{( '<.90' if x['pos']<0.90 else '.90-.93')}", 20)
    show_slice("S17 E1B time", [x for x in kept if x["leg"] == "E1B_30S"],
               lambda x: f"{x['eh']}:{'00-30' if x['em']<30 else '30-00'}", 30)
    show_slice("S18a vol1m x 1mlegs", [x for x in kept if x["tf"] == 60],
               lambda x: f"v{('lo' if (x['vol'] or 0)<V1_LO else ('mid' if x['vol']<V1_HI else 'hi'))}", 50)
    show_slice("S18b vol30 x E1B", [x for x in kept if x["leg"] == "E1B_30S"],
               lambda x: f"v{('lo' if (x['vol'] or 0)<V3_LO else ('mid' if x['vol']<V3_HI else 'hi'))}", 30)
    show_slice("S19 Fri-late", kept, lambda x: (
        "Fri20+" if (x["wd"] == "Fri" and x["eh"] >= 20) else ("Fri" if x["wd"] == "Fri" else "other")), 30)
    show_slice("S20 contig_expiry", kept, lambda x: f"cont{x['cont']}", 30)
    show_slice("S21 tmode x calm x 1m", [x for x in kept if x["tf"] == 60],
               lambda x: f"{x['tmode']}:{'c' if x['calm'] else 'n'}", 50)
    show_slice("S22a h06 x leg", [x for x in kept if x["eh"] == 6],
               lambda x: x["leg"], 15)
    show_slice("S22b h15 x leg", [x for x in kept if x["eh"] == 15],
               lambda x: x["leg"], 15)
    show_slice("S23 E1B tmode", [x for x in kept if x["leg"] == "E1B_30S"],
               lambda x: x["tmode"], 30)


if __name__ == "__main__":
    main()

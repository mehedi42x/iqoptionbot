#!/usr/bin/env python3
"""Equity chart: MaxFade v2 vs v3 @85%."""
import csv

W, H, PL, PR, PT, PB = 900, 420, 60, 20, 30, 40


def equity(path):
    eq, out = 0.0, [0.0]
    for t in csv.DictReader(open(path)):
        eq += 0.85 if t["result"] == "WIN" else (-1 if t["result"] == "LOSS" else 0)
        out.append(eq)
    return out


v2 = equity("backtest_ms1__trades_60s.csv")
v3 = equity("backtest_ms1__trades_60s.csv")
allv = v2 + v3
mn, mx = min(allv), max(allv)
pad = (mx - mn) * 0.08
mn, mx = mn - pad, mx + pad


def X(i, n):
    return PL + i / max(n - 1, 1) * (W - PL - PR)


def Y(v):
    return PT + (1 - (v - mn) / (mx - mn)) * (H - PT - PB)


def path(data):
    n = len(data)
    return "M" + " L".join(f"{X(i, n):.1f},{Y(v):.1f}" for i, v in enumerate(data))


svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">',
       f'<rect width="{W}" height="{H}" fill="#0f1117"/>',
       f'<text x="{W//2}" y="20" fill="#e8e8e8" font-size="15" text-anchor="middle">MaxFade v3 বনাম মাল্টি-সিগন্যাল v1 — ইক্যুইটি ($1, পেআউট 85%)</text>']
for f in (0, 0.25, 0.5, 0.75, 1.0):
    v = mn + (mx - mn) * f
    svg.append(f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" stroke="#2a2d3a" stroke-width="1"/>')
    svg.append(f'<text x="{PL-8}" y="{Y(v)+4:.1f}" fill="#8a8fa3" font-size="10" text-anchor="end">${v:,.0f}</text>')
svg.append(f'<path d="{path(v2)}" fill="none" stroke="#7aa2f7" stroke-width="1.6"/>')
svg.append(f'<path d="{path(v3)}" fill="none" stroke="#9ece6a" stroke-width="1.6"/>')
svg.append(f'<text x="{PL+10}" y="{H-12}" fill="#7aa2f7" font-size="12">━ MS1: 11,078 ট্রেড, 59.65%, +$1,098</text>')
svg.append(f'<text x="{PL+380}" y="{H-12}" fill="#9ece6a" font-size="12">━ MS1: 11,078 ট্রেড, 59.65%, +$1,098</text>')
svg.append("</svg>")
open("chart_ms1.svg", "w").write("\n".join(svg))
print("wrote chart_ms1.svg")

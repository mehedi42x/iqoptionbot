#!/usr/bin/env python3
"""Full equity comparison incl. MaxFade v2 @85%, $1 (stdlib only)."""
import csv

PAYOUT = 0.85
SERIES = [
    ("backtest_v1_85_trades_60s.csv", "V1", "#dc2626"),
    ("backtest_v2_85_trades_60s.csv", "V2", "#f59e0b"),
    ("backtest_mf_full_trades_60s.csv", "MFv1 FULL", "#3b82f6"),
    ("backtest_mf_trades_60s.csv", "MFv1 TRIM", "#a855f7"),
    ("backtest_mfv2_trades_60s.csv", "MFv2 (W7)", "#16a34a"),
]


def daily_equity(path):
    day_net = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            d = r["entry_dt"][:10]
            day_net[d] = day_net.get(d, 0.0) + (
                PAYOUT if r["result"] == "WIN" else (-1.0 if r["result"] == "LOSS" else 0.0))
    days = sorted(day_net)
    eq, out = 0.0, []
    for d in days:
        eq += day_net[d]
        out.append((d, eq))
    return out


def main():
    curves = [(label, color, daily_equity(p)) for p, label, color in SERIES]
    days = sorted(set(d for _, _, c in curves for d, _ in c))

    def at(curve, day):
        v = 0.0
        for d, e in curve:
            if d <= day:
                v = e
            else:
                break
        return v

    eqs = [[at(c, d) for d in days] for _, _, c in curves]
    W, H, PL, PR, PT, PB = 960, 440, 64, 20, 34, 46
    lo = min(min(e) for e in eqs)
    hi = max(max(e) for e in eqs)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    n = len(days)

    def X(i):
        return PL + (W - PL - PR) * i / max(1, n - 1)

    def Y(v):
        return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))

    grid = []
    for k in range(7):
        v = lo + (hi - lo) * k / 6
        grid.append(f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" stroke="#e5e7eb"/>'
                    f'<text x="{PL-8}" y="{Y(v)+4:.1f}" font-size="11" text-anchor="end" fill="#6b7280">${v:.0f}</text>')
    xt = []
    for i in range(n):
        if i % 7 == 0 or i == n - 1:
            xt.append(f'<text x="{X(i):.1f}" y="{H-24}" font-size="10" text-anchor="middle" fill="#6b7280">{days[i][5:]}</text>')
    xt.append(f'<text x="{W-PR}" y="{H-8}" font-size="11" text-anchor="end" fill="#6b7280">date (2026)</text>')
    paths = []
    for (label, color, _), e in zip(curves, eqs):
        paths.append('<path d="M' + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(e))
                     + f'" fill="none" stroke="{color}" stroke-width="2.5"/>')
    legend = []
    lx = PL + 10
    for (label, color, _), e in zip(curves, eqs):
        legend.append(f'<circle cx="{lx}" cy="40" r="5" fill="{color}"/><text x="{lx+8}" y="44">{label}: ${e[-1]:+.0f}</text>')
        lx += 190

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">
<rect width="{W}" height="{H}" fill="white"/>
<text x="{W//2}" y="20" font-size="14" font-weight="bold" text-anchor="middle" fill="#111827">All strategies — 60s @85% payout, $1 stake</text>
{''.join(grid)}
<line x1="{PL}" y1="{Y(0):.1f}" x2="{W-PR}" y2="{Y(0):.1f}" stroke="#9ca3af" stroke-dasharray="4,3"/>
{''.join(paths)}
{''.join(xt)}
<g font-size="12" fill="#111827">{''.join(legend)}</g>
</svg>'''
    open("chart_mfv2.svg", "w").write(svg)
    print("wrote chart_mfv2.svg")


if __name__ == "__main__":
    main()

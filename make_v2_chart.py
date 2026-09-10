#!/usr/bin/env python3
"""V1 vs V2 date-aligned equity chart (stdlib only)."""
import csv
from datetime import datetime

PAYOUT = 0.80


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
    v1 = daily_equity("backtest_trades_60s.csv")
    v2 = daily_equity("backtest_v2_trades_60s.csv")
    days = sorted(set([d for d, _ in v1]) | set([d for d, _ in v2]))

    def at(curve, day):
        v = 0.0
        for d, e in curve:
            if d <= day:
                v = e
            else:
                break
        return v

    e1 = [at(v1, d) for d in days]
    e2 = [at(v2, d) for d in days]
    W, H, PL, PR, PT, PB = 960, 420, 60, 20, 34, 46
    lo = min(min(e1), min(e2))
    hi = max(max(e1), max(e2))
    pad = (hi - lo) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    n = len(days)

    def X(i):
        return PL + (W - PL - PR) * i / max(1, n - 1)

    def Y(v):
        return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))

    def path_of(e):
        return "M" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(e))

    grid = []
    for k in range(6):
        v = lo + (hi - lo) * k / 5
        grid.append(f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" stroke="#e5e7eb"/>'
                    f'<text x="{PL-8}" y="{Y(v)+4:.1f}" font-size="11" text-anchor="end" fill="#6b7280">{v:.0f}R</text>')
    xt = []
    for i in range(n):
        if i % 7 == 0 or i == n - 1:
            xt.append(f'<text x="{X(i):.1f}" y="{H-24}" font-size="10" text-anchor="middle" fill="#6b7280">{days[i][5:]}</text>')
    xt.append(f'<text x="{W-PR}" y="{H-8}" font-size="11" text-anchor="end" fill="#6b7280">date (2026)</text>')

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">
<rect width="{W}" height="{H}" fill="white"/>
<text x="{W//2}" y="20" font-size="14" font-weight="bold" text-anchor="middle" fill="#111827">V1 vs V2 Equity — 60s expiry @80% payout (date-aligned, R multiples)</text>
{''.join(grid)}
<line x1="{PL}" y1="{Y(0):.1f}" x2="{W-PR}" y2="{Y(0):.1f}" stroke="#9ca3af" stroke-dasharray="4,3"/>
<path d="{path_of(e1)}" fill="none" stroke="#dc2626" stroke-width="2.5"/>
<path d="{path_of(e2)}" fill="none" stroke="#16a34a" stroke-width="2.5"/>
{''.join(xt)}
<g font-size="12" fill="#111827">
<circle cx="{PL+10}" cy="40" r="5" fill="#dc2626"/><text x="{PL+20}" y="44">V1 (emacombo): {e1[-1]:+.1f}R, n=4301</text>
<circle cx="{PL+280}" cy="40" r="5" fill="#16a34a"/><text x="{PL+290}" y="44">V2 (emacombo_v2): {e2[-1]:+.1f}R, n=4814</text>
</g>
</svg>'''
    open("chart_v1v2.svg", "w").write(svg)
    print("wrote chart_v1v2.svg")

    # daily stats for the report
    for name, path in (("V1", "backtest_trades_60s.csv"), ("V2", "backtest_v2_trades_60s.csv")):
        day_net = {}
        day_n = {}
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                d = r["entry_dt"][:10]
                day_net[d] = day_net.get(d, 0.0) + (
                    PAYOUT if r["result"] == "WIN" else (-1.0 if r["result"] == "LOSS" else 0.0))
                day_n[d] = day_n.get(d, 0) + 1
        vals = list(day_net.values())
        import statistics
        green = sum(1 for v in vals if v > 0)
        print(f"{name}: days={len(vals)} trades/day={sum(day_n.values())/len(day_n):.1f} "
              f"mean={statistics.mean(vals):+.2f}R median={statistics.median(vals):+.2f}R "
              f"green={green}/{len(vals)} ({100*green/len(vals):.1f}%) min={min(vals):+.1f} max={max(vals):+.1f}")


if __name__ == "__main__":
    main()

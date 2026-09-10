#!/usr/bin/env python3
"""Generate SVG charts for the backtest report (stdlib only)."""
import csv

TRADES = "backtest_trades_60s.csv"
PAYOUT = 0.80


def load():
    with open(TRADES, newline="") as f:
        return list(csv.DictReader(f))


def equity_svg(trades, path):
    W, H, PL, PR, PT, PB = 960, 420, 60, 20, 30, 40
    all_eq, rev_eq, mom_eq = [0.0], [0.0], [0.0]
    for t in trades:
        r = PAYOUT if t["result"] == "WIN" else (-1.0 if t["result"] == "LOSS" else 0.0)
        all_eq.append(all_eq[-1] + r)
        rev_eq.append(rev_eq[-1] + (r if t["module"] == "REVERSAL" else 0.0))
        mom_eq.append(mom_eq[-1] + (r if t["module"] == "MOMENTUM" else 0.0))
    n = len(trades)
    lo = min(min(all_eq), min(rev_eq), min(mom_eq))
    hi = max(max(all_eq), max(rev_eq), max(mom_eq))
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad

    def X(i):
        return PL + (W - PL - PR) * i / n

    def Y(v):
        return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))

    def path_of(eq):
        step = max(1, len(eq) // 600)
        pts = [f"{X(i):.1f},{Y(eq[i]):.1f}" for i in range(0, len(eq), step)]
        pts.append(f"{X(n):.1f},{Y(eq[-1]):.1f}")
        return "M" + " L".join(pts)

    # gridlines
    grid = []
    for k in range(6):
        v = lo + (hi - lo) * k / 5
        grid.append(f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" stroke="#e5e7eb" stroke-width="1"/>'
                    f'<text x="{PL-8}" y="{Y(v)+4:.1f}" font-size="11" text-anchor="end" fill="#6b7280">{v:.0f}R</text>')
    xticks = []
    for k in range(7):
        i = n * k // 6
        xticks.append(f'<text x="{X(i):.1f}" y="{H-12}" font-size="11" text-anchor="middle" fill="#6b7280">#{i}</text>')

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">
<rect width="{W}" height="{H}" fill="white"/>
<text x="{W//2}" y="18" font-size="14" font-weight="bold" text-anchor="middle" fill="#111827">Equity Curve — 60s expiry @80% payout (R multiples, $1 stake)</text>
{''.join(grid)}
<line x1="{PL}" y1="{Y(0):.1f}" x2="{W-PR}" y2="{Y(0):.1f}" stroke="#9ca3af" stroke-width="1" stroke-dasharray="4,3"/>
<path d="{path_of(all_eq)}" fill="none" stroke="#111827" stroke-width="2"/>
<path d="{path_of(rev_eq)}" fill="none" stroke="#16a34a" stroke-width="2"/>
<path d="{path_of(mom_eq)}" fill="none" stroke="#dc2626" stroke-width="2"/>
{''.join(xticks)}
<g font-size="12" fill="#111827">
<circle cx="{PL+10}" cy="34" r="5" fill="#111827"/><text x="{PL+20}" y="38">ALL: {all_eq[-1]:+.1f}R</text>
<circle cx="{PL+150}" cy="34" r="5" fill="#16a34a"/><text x="{PL+160}" y="38">REVERSAL-only: {rev_eq[-1]:+.1f}R</text>
<circle cx="{PL+360}" cy="34" r="5" fill="#dc2626"/><text x="{PL+370}" y="38">MOMENTUM-only: {mom_eq[-1]:+.1f}R</text>
</g>
<text x="{W-PR}" y="{H-12}" font-size="11" text-anchor="end" fill="#6b7280">trade number (time order)</text>
</svg>'''
    open(path, "w").write(svg)
    print("wrote", path)


def hourly_svg(trades, path):
    from collections import defaultdict
    W, H, PL, PR, PT, PB = 960, 440, 50, 20, 50, 60
    hours = [str(h) for h in range(24) if str(h) not in ()]
    # only traded hours (skip 3,20,21,22 by strategy)
    g = defaultdict(list)
    for t in trades:
        g[(t["module"], t["sig_hour"])].append(t)

    def wr(rows):
        w = sum(1 for r in rows if r["result"] == "WIN")
        l = sum(1 for r in rows if r["result"] == "LOSS")
        return 100 * w / (w + l) if (w + l) else 0

    traded_hours = sorted({t["sig_hour"] for t in trades}, key=int)
    BE = 100 / (1 + PAYOUT)
    lo, hi = 40, 75

    def Y(v):
        return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))

    bw = (W - PL - PR) / len(traded_hours)
    bars = []
    for k, h in enumerate(traded_hours):
        x0 = PL + k * bw
        for j, mod in enumerate(("REVERSAL", "MOMENTUM")):
            rows = g[(mod, h)]
            v = wr(rows)
            color = "#16a34a" if mod == "REVERSAL" else "#f59e0b"
            bx = x0 + 4 + j * ((bw - 8) / 2)
            bars.append(f'<rect x="{bx:.1f}" y="{Y(v):.1f}" width="{(bw-8)/2:.1f}" height="{Y(lo)-Y(v):.1f}" fill="{color}" opacity="0.9">'
                        f'<title>{mod} h={h}: WR={v:.1f}% n={len(rows)}</title></rect>')
        bars.append(f'<text x="{x0+bw/2:.1f}" y="{H-38}" font-size="10" text-anchor="middle" fill="#374151">{h}h</text>')
        n = len([t for t in trades if t["sig_hour"] == h])
        bars.append(f'<text x="{x0+bw/2:.1f}" y="{H-24}" font-size="9" text-anchor="middle" fill="#9ca3af">n={n}</text>')

    grid = []
    for v in (40, 45, 50, 55, 60, 65, 70, 75):
        grid.append(f'<line x1="{PL}" y1="{Y(v):.1f}" x2="{W-PR}" y2="{Y(v):.1f}" stroke="#e5e7eb"/>'
                    f'<text x="{PL-6}" y="{Y(v)+4:.1f}" font-size="10" text-anchor="end" fill="#6b7280">{v}%</text>')

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">
<rect width="{W}" height="{H}" fill="white"/>
<text x="{W//2}" y="20" font-size="14" font-weight="bold" text-anchor="middle" fill="#111827">Win-rate by Signal Hour (UTC) — 60s expiry</text>
<g font-size="12" fill="#111827">
<rect x="{PL}" y="28" width="12" height="12" fill="#16a34a"/><text x="{PL+16}" y="38">REVERSAL</text>
<rect x="{PL+120}" y="28" width="12" height="12" fill="#f59e0b"/><text x="{PL+136}" y="38">MOMENTUM</text>
</g>
{''.join(grid)}
<line x1="{PL}" y1="{Y(BE):.1f}" x2="{W-PR}" y2="{Y(BE):.1f}" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="6,3"/>
<text x="{W-PR}" y="{Y(BE)-4:.1f}" font-size="11" text-anchor="end" fill="#dc2626">breakeven @80% = {BE:.1f}%</text>
{''.join(bars)}
</svg>'''
    open(path, "w").write(svg)
    print("wrote", path)


if __name__ == "__main__":
    trades = load()
    equity_svg(trades, "chart_equity.svg")
    hourly_svg(trades, "chart_hourly.svg")

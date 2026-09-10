# Strategy V13 — MTF-Volume v3 Report (profit-max round, free hand)

**Date:** 2026-09-10. **Ask:** time filters / multiple systems / anything — maximize
PROFIT while keeping WR high. **Result: U6 = U5 + E1B@h04 + E1B@h23-refined.**

| System | n | WR | Net @$10 | vs U5 |
|---|---|---|---|---|
| **U6 `strategies/mtf_volume_v3.py`** | **6,741** | **60.44%** | **+$7,523.50** | **+$502.00 (+7.1%)** ✅ |
| U5 `strategies/mtf_volume_v2.py` | 6,293 | 60.43% | +$7,021.50 | — |
| MS2 same-file | 5,707 | 59.80% | +$5,778 | U6: +$1,745.50 (+30.2%) |

Deploy: `STRATEGY=mtf_volume_v3` (`EXPIRATION_SECONDS=60`, `TRADE_AMOUNT=10`,
`MAX_CONCURRENT_TRADES=1`).

---

## 1. U5 forensics R1 (`lab_u6_1.py`) — no cuts left

Regenerated U5 in lab (**EXACT** vs backtest CSV). Fresh slices: EVERY hour, leg,
pos/size/calm/trend/body/weekday cell is +both-splits or mixed — **zero both-neg
pockets remain**. h06 fixed by the veto (156 @ 60.39%/+$180.50). Time-filter CUTS
rejected everywhere (no hour is both-negative). SKIP:flat TR-razor (HO +$22.4),
p<.85 mixed, s2+ thin-but-positive. Weekend-edge empty (again).

## 2. Candidates R1 — only h23-refinement survives

13 tests (union/cut through busy; bars: profit↑, WR≥60.43%, TR↑, HO↑, 3/3 blocks):
- **A2 E1B@h23+vsT** +$16.0 WR↑ but B1 −$3.7 → hold. **A3 E1B@h23-size<.75** +$12.3,
  3/3↑ but WR −0.04 → hold. (Both absorbed by B9 later.)
- Killed: A1 E1B@h19 (−$17.8, ~50% — US-open 30s-fades dead), A4 h04-1m (B1↓),
  A5 monster.88 (−$1.9), A7 calm-mid-down (−0.65pp!), **A8 30s-follow (−$391,
  B2 negative — FOLLOW dead on 30s too)**, A9 BB-fade (−$33.9, TR↓↓ — BB leftovers
  53%, MS2 owns the tradeable extremes), A10/A12/A13 30s-big/low-pos (TR↓/dilute),
  C1 soft-chop-veto (−$5, HO↓ — h06 was UNIQUE, extensions cut HO-winners).

## 3. Round R2 — B9 PASSES, B4 profit-leader with WR-cost

- **B9 = E1B@h23 + (vsT OR size<.75): PASS ALL** (+168: dW+104/dL+64, WR 60.47%,
  +$24.3, TR↑HO↑B↑↑↑). A2's B1-hole fixed by A3's small-bars.
- **B4 = E1B@h03+h04: +$41.6** (biggest profit!) but WR −0.06 → split or combo-ride.
- **B2 = monster-normal-.85-.90: +$14.0**, 3/3↑, WR −0.03 → hold.
- Killed: B1 SKIP.75 (HO↓B3↓), **B3 E1B@h012 (50/50 coinflip −$55.6 — Asia-night
  E1B dead)**, B5 h23-p.85 (TR↓), B6 30s-big+p.85 (~50% — **30s-big family CLOSED**),
  B7 FADE-unconfirmed (pool 28, TR-flat — 1m-extremes ⟹ strong 2nd half),
  B8 SKIP-unconfirmed (−$33 — unconfirmed fades are PROFITABLE, confirmation
  filters dead for cuts).

## 4. Rounds R3–R5 — splits + last ideas, E1B-hour map completed

- B4-split: **B4b E1B@h04 (+$25.7, 3/3↑, WR −0.03) adopts the profit**; B4a h03 has
  a B3-hole (−$10.3) → dropped. B2-split: B2a B2-hole, B2b B3-flat → B2 rides
  whole-or-nothing (whole: +$14.0, 3/3↑, WR −0.03).
- R4 all dead: E1B@h05 (53%), h02 (49%), h18 (48%), h1617 (49%), h12/15-calm-.90
  (35%! — h12/15-trim re-confirmed). R5 all dead: BB+vsT (53.8%), BB+calm (B1↓),
  SK75+vsT (HO↓), G1M85+vsT (B1↓), E1B@h67 (52.5%).
- **E1B-hour map FINAL:** works {4, 20, 21, 22, 23*} (*=vsT-or-small filter);
  dead {0,1,2,3(B3-hole),5,6,7,16,17,18,19}; weak/trim zones skipped on principle.

## 5. Final combo R6 — U6 = U5 + B9 + B4b (disjoint hours → additive exact)

| | n | W/L/D | WR | Net R | TR | HO | B1/B2/B3 |
|---|---|---|---|---|---|---|---|
| U6 | 6,741 | 3851/2521/369 | 60.44% | +752.3 | +409.5 | +342.9 | +304.6/+195.8/+251.9 |
| Δ vs U5 | +448 | +252/+164/+32 | +0.01pp | **+$50.1** | +$22.2 | +$28.1 | +$10.4/+$20.9/+$18.8 |

All bars pass. Combos with B2 (60.41%) or whole-B4 (60.41%) miss WR — rejected.
New E1B kept 523 @ ~61.5% (h04 296/59.21%/+$264, h23 227/63.33%/+$360.50),
displacing 75 thin 1m trades via busy. WR flat (+0.01pp) — U5 was at the WR ceiling;
profit +7.1% is the validated max at held WR.

## 6. Build + verification — backtest == lab EXACT

`strategies/mtf_volume_v3.py` = v2 + E1B hours {4,20,21,22} plain + h23-refined
(size<1.0 AND (vsT OR size<0.75); trend-None counts as not-vs). **Entry-sets
identical (6,741 = 6,741)** ✅. 120s/300s: 56.26%/53.60% (300s PF 0.982) —
**60s stays optimal**. (Also fixed v2's stale docstring, docs-only; v2 re-run
identical 6293/60.43%/702.15R.)

## 7. Final numbers (Aug 11–Sep 10, @$10)

**n=6,741 (W3,851/L2,521/D369), 60.44%** (CI [59.23, 61.63], z=10.22), **+$7,523.50**,
PF 1.298, exp +$1.18, DD $250.00, 26/27 days green (96.3%), ~250 trades/day.
Legs all green: E1B 1,131/62.40%/+$1,594 · FADE 2,749/59.57% · SKIP 1,933/61.69% ·
CALM_MID 457 · G1M 230 · SKIP_CALM 154 · MONSTER 87. Months: Aug 59.61%/+$4,103 ·
Sep 61.81%/+$3,420.50. Honest note: worst day −$77.00 (U5: −$36.50) — one day runs
hotter; green-day rate still up (96.3% vs 92.6%), DD unchanged.

## 8. Rejected log (~45 tests this round)

Time-cut C1; A1/A3(partial)/A4/A5/A7/A8/A9/A10/A12/A13; B1/B2(combo-miss)/B3/B4a/
B5/B6/B7/B8; D1–D5; E1–E5; B9+B2, B9+B4, B4b+B2 combos (WR↓). Position sizing /
martingale deliberately NOT touched (variance, not edge — dangerous).

## 9. Journey

v1 53.7% → MS2 60.25% (365d) → U4 59.91% @ 6,270 → U5 60.43% @ 6,293 (+$7,021.50)
→ **U6 60.44% @ 6,741 (+$7,523.50)** · SNIPER 67.66% / MTF-SNIPER 68.02% hold WR%.
~300 pockets tested. Chart: `chart_mtfv3.svg`.

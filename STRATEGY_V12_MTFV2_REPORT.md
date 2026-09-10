# Strategy V12 — MTF-Volume v2 Report (comb operation on U4 losers)

**Date:** 2026-09-10. **Ask:** চিরুনি অভিযান — why did MTF-volume's 2,382 losses lose,
flip them if possible, try various logics, raise W AND lower L.
**Result: U5 swap passes the strict W↑L↓ bars — new money champion.**

| System | n | WR | Net @$10 | dW/dL vs U4 |
|---|---|---|---|---|
| **U5 `strategies/mtf_volume_v2.py`** | **6,293** | **60.43%** | **+$7,021.50** | **+39 / −25** ✅ |
| U4 `strategies/mtf_volume.py` | 6,270 | 59.91% | +$6,440 | — |
| MS2 same-file | 5,707 | 59.80% | +$5,778 | — |

Deploy: `STRATEGY=mtf_volume_v2` (`EXPIRATION_SECONDS=60`, `TRADE_AMOUNT=10`,
`MAX_CONCURRENT_TRADES=1`). U5 beats MS2 same-file by **+586 trades, +0.63pp,
+$1,243.50 (+21.5%)**.

---

## 1. Forensics P1 (`lab_comb_mtf.py`) — where the losses live

Regenerated U4 in lab incl. signal-time features; **verify vs backtest CSV EXACT**
(6,270 entries + legs, digit-for-digit). Sliced by 24 feature families
(TRAIN Aug 11–31 / HO Sep 1–10; cut-bar = negative BOTH splits):

- All 7 legs +both splits. FADE holds 48% of losses (1,152/2,382), SKIP 30%.
- NO hour, pos-bucket, size-bucket, calm, trend, body, wick, weekday, ATR-level,
  runup, volume, or Friday-late slice is both-negative. System is comb-resistant
  (4th hunt on this lineage — easy cuts long gone).
- Soft-but-mixed (TR/HO disagree → NO cut): h06 (TR +$9.3/HO −$18.1), h15, h16,
  h17, SKIP-low-pos, FADE-big (s≥1.5: TR +$5/HO −$14.3), E1B-midsize, 1m-vol-high
  (HO −$3.3 — volume dead AGAIN, consistent with the grand assault).
- Weekend-edge: EMPTY — all 6,270 expiries contiguous; gap-entries = 2. Nothing to fix.
- Only both-neg coarse cell: G1M@h15 (n=31, HO ≈ breakeven) — too tiny to ship.

## 2. Probes P2 (`lab_comb_mtf2.py`) — fine cells, adds, vetoes

**CUT-confirmed (both-neg, n≥50):** h06-FADE-with-T (n=69, 43.5%, −$13.5),
h06-FADE-big-size (n=72, 42.3%, −$15.5, overlap 17 → union C12e n=124, −$26.8).
Everything else mixed: E1B cells, SKIP cells, FADE-big × trend/calm, CALM_MID
variants (CM-CALL-vs razor −$1.5 with failing blocks → rejected), vhi × trend,
h16/h17 cells, hour-start mm<5 (+both — hypothesis killed).

**ADDS (union through busy):** only **L1a = E1B@h20** passes everything (+147 net:
dW+91/dL+46, WR +0.15pp, TR +$16.1, HO +$15.2, 3/3 blocks). L1b = E1B@h23 dilutes
(WR −0.02 → rejected); L2/L3/L4/L5 lower bars dilute or lose TRAIN; L10 pocket is
100% busy-shadowed (0 kept). **VETOES:** 2nd-half-30s opposition pool = 8 (useless);
1st-half veto loses both splits; ctx-opposition veto mixed; N2-hour-start cut loses.

## 3. Swaps P3 (`lab_comb_mtf3.py`) — the strict W↑L↓ bars

Pure cuts fail W↑, pure adds fail L↓ by construction — only swaps/flips can pass.
Flips fail: C-pockets are ~50% on TRAIN (payout drag, not signal) — flipping is
neutral/negative there (F1 TR flat, F2/F12 TR down). CM-CALL-vs rejected (blocks 1/3).
**S3 = L1a + C12e PASSES ALL:** dW=+39, dL=−25, WR +0.51pp, TR +$20.4, HO +$37.7,
3/3 blocks up. (sh-variant S4 ≈ identical; eh-adopted as probe-exact, +1 trade better.)

Mechanism (double win): E1B@h20 adds 202 kept @ 64.4% (best E1B hour — h20 is MS2's
thinnest SKIP hour, 30s-fades exploit it differently) while displacing 55 thin
SKIP-h20 trades; C12e deletes 124 rotten h06 fades. h06 fixed: was 280 @ 52.35%/
−$88 → now 156 @ 60.39%/+$180.50.

## 4. Build + verification — backtest == lab EXACT (after honest ghost-hunt)

`strategies/mtf_volume_v2.py` = U4 + `E1B_HOURS += {20}` + H06 veto (normal-FADE
entries at 06:xx skipped when fade rides WITH 1m-trend — warmup counts as
with-side, as validated — or signal range/ATR60 ≥ 1.5).

Verify found exactly ONE diff: Fri Sep-4 20:59:00 E1B (lab kept, backtest dropped).
Root cause: MS2-signal at the Friday-close edge has no 1m-expiry (dropped as
`incomplete` in backtest, absent from lab raw) but its live-correct tie-shadow
still blocks the same-ts E1B in the strategy — while lab's 30s-fallback kept it.
Fix applied to the LAB (MS2-signal-ts set incl. Friday ghosts now tie-blocks 30s
adds — matches strategy + live slot behavior). After fix: **entry-sets identical,
6,293 = 6,293** ✅. U4's EXACT verify unaffected (re-confirmed).

120s/300s re-check: 56.43%/53.53% (300s PF 0.979 < 1) — **60s stays optimal**.

## 5. Final numbers (Aug 11–Sep 10, @$10)

**n=6,293 (W3,599/L2,357/D337), 60.43%** (CI [59.18, 61.66], z=9.87), **+$7,021.50**,
PF 1.298, exp +$1.18, DD $250.00, 25/27 days green (92.6%), worst day −$36.50
(was −$85.50), ~233 trades/day. Legs all green: FADE 2,793/59.59%/+$2,739 ·
SKIP 1,933/61.69%/+$2,579.50 · E1B 608/63.67%/+$969.50 (h20 64.36% / h21 62.36% /
h22 64.25%) · CALM_MID 459 · G1M 256 · SKIP_CALM 154 · MONSTER 90.
Months: Aug 59.59%/+$3,881.50 · Sep 61.89%/+$3,140. Veto fires 124× (lab pool match).

## 6. Rejected under bars (transparency log)

C3 CM-CALL-vs (blocks 1/3, razor); F1/F2/F12 flips (TRAIN flat/down — payout-drag
pockets, not signals); S1/S2 incl. C3 (dL +32/0); L1-full h20+23 (dL +126,
unpairable); L1b h23 (WR↓); L2/L3/L4/L5 (TRAIN↓ or dilute); L10 (shadowed);
M1 (pool 8), M2 (loses both), M3 (mixed), N2 (loses both); MS2 1m-bar re-tunes
deliberately NOT attempted (31-day window cannot override 365d validation).

## 7. Journey

v1 53.7% → MS2 60.25% (365d) → U4-MTF 59.91% @ 6,270 → **U5-MTF 60.43% @ 6,293
(+$7,021.50)** · SNIPER 67.66% / MTF-SNIPER 68.02% hold the WR% crowns.
~260 pockets tested. Chart: `chart_mtfv2.svg`.

# Strategy V11 — MTF Report (30s + 60s Multi-Timeframe)

**Date:** 2026-09-10. **Question:** user uploaded 30s + 60s data — can multi-timeframe
keep BOTH win rate and trade count maximal? **Answer: YES — two new champions.**

| System | File | n | WR | Net @$10 | Verdict |
|---|---|---|---|---|---|
| **MTF-Volume (U4)** | `strategies/mtf_volume.py` | 6,270 | **59.91%** | **+$6,440** | beats MS2 same-file on ALL FOUR (count/WR/TR/HO) |
| **MTF-Sniper (S30a)** | `strategies/mtf_sniper.py` | 403 | **68.02%** | +$953.50 | window WR-king (HO 73.33%) |
| MS2 same-file baseline | `strategies/multisignal_v2.py` | 5,707 | 59.80% | +$5,778 | beaten on all four |

Deploy: `.env` → `STRATEGY=mtf_volume` (money) or `STRATEGY=mtf_sniper` (WR%),
`EXPIRATION_SECONDS=60`, `TRADE_AMOUNT=10`, `MAX_CONCURRENT_TRADES=1`.

---

## 1. Data (user-uploaded, origin/main `b0ea621`)

| File | Rows (used) | Span (UTC) |
|---|---|---|
| `candles_asset_1861_30s_30d.csv` | 43,942 | Aug 20 05:00:30 → Sep 10 11:14:00 |
| `candles_asset_1861_60s_30d.csv` | 31,999 | Aug 11 05:50 → Sep 10 11:12 |

QC: forming tail row dropped per file (lab + backtest identical); 30s `:00/:30`
balanced (21,971/21,972); 30s→1m rebuild matches 1m file except the forming tail;
3 weekend gaps; new-60s ∩ old-365d-60s = 31,824 rows with 1 tail diff.
Window = Aug 20–Sep 10 (30s coverage). **TRAIN = Aug 20–31, HO = Sep 1–10.**

Mechanics (unchanged): 60s expiry, 85% payout, $1 stake in lab (=R), MAX_CONCURRENT=1
(`busy_until`) replicated in every lab test.

## 2. Round 1 — survey (`lab_mtf.py`)

Baseline **MS2-on-window**: n=3,986, 59.18%, +$360.5R (TR 57.45%/+$120.1, HO 60.93%/+$240.4).

| Test | What | Result | Verdict |
|---|---|---|---|
| A1–A4 | plain 30s fades ≥0.85/0.90/0.93/0.95 | 55.3%→57.5%, all splits + | work, but weaker than 1m |
| A0 | 30s fades WEAK-hours only | 50.6%/49.7%, all blocks − | **weak dead on 30s too** |
| E1b | 30s sniper h21/22 + size<1.0 | TR 62.01%, HO 67.49%, n=849 | **strong, 3/3 +** |
| F-with/vs/flat | 30s ≥0.93 × 1m-trend | vs 58.1/59.3 > flat > with 54.5% | same structure as 1m |
| B1/B2 | 30s+1m confluence | ≈58.5%, +1.5pp over plain 30s | confluence works |
| G1 | 1m-mid + fresh-30s confirm | 59.7/58.1, n=314, +++ | marginal-add candidate |
| D2 | MS2 signals, entry delayed one 30s | 49.6%/51.6%, −$149/−$83 | **delayed entry DESTROYS the edge → enter immediately** |

## 3. Round 2 — tuning + ports + sniper+ (`lab_mtf2.py`)

**30s hour-tiers transfer:** skip-0.80 (59.5/63.3%), monster-0.90 (+ both),
h12/15-trim **confirmed on 30s** (TR +$0.4 razor / HO −$3.0, 2/3 blocks −).
**30s calm-mid HURTS** (ablation: without it +$353.4 vs with +$338.5 → cut from 30s).

**Standalone 30s systems CANNOT beat MS2-window** (definitive):
H1 full-port (count +54% but WR −2pp, profit −$22), H2 vs-only (count −28%,
profit −$97 — dead middle), H2b (WR −0.5pp, profit −$17), H3 (fails all three).

**Unions (busy_until):** U1 MS2+B2 (count +20%, profit +$22, **WR −0.6pp — fail**),
U2 MS2+A3 (count +68%, profit +$55, **WR −1.6pp — fail**). Low-WR adds dilute:
only HIGH-WR legs can join MS2. G1m (overlap-excluded): +256 @ 59.6%, micro-pass.

**Sniper+:** S30a E1b+vsT (HO **73.33%**), S30b E1b+conf (70.10%), S30c E1b+calm
(71.64%), S30d E1b-plain (67.49%, n=849). All: HO-n ≥ 150, 3/3 blocks +,
≈19–22 trades/day ≈ 1m-sniper rate. Ranked by HO-WR → **S30a champion**.

## 4. Round 3 — the union that works

| System | FULL | vs MS2-window (3,986 / 59.18% / +$360.5) |
|---|---|---|
| **U4 = MS2 + E1b-30s + G1m** | **4,549 / 59.40% / +$426.7** | count **+14.1%**, WR **+0.22pp**, TR **+$29.5**, HO **+$36.7** ✅ all four |
| U3 = MS2 + E1b | 4,293 / ≈59.4% / +$401.5 | passes; U4 adds G1m on top |

Exact (kept, post-busy): U4 n=4,549 W2,562/L1,751/D236; TR 57.77%/+$149.6;
HO 61.06%/+$277.1; blocks B1 +$58.4 / B2 +$162.2 / B3 +$206.1; dW=+312, dL=+199.

## 5. Build — live strategies + MTF backtest

- `strategies/mtf_volume.py` (U4): MS2 1m-legs verbatim + E1B 30s-leg (entry-h21/22,
  30s-pos ≥ 0.80, 30s-range/1m-ATR60mean < 1.0) + G1M leg (1m-mid 0.85–0.93 +
  fresh second-half 30s ≥ 0.90 same side). Tie order MS2 > E1B > G1M enforced.
- `strategies/mtf_sniper.py` (S30a): E1B + 1m-vs-trend (SMA50/20).
- `backtest.py --mtf`: interleaved 30s+60s feed (60s-first at :00), settlement in
  entry TF, shared busy_until, per-TF gap flags, `tf` column + `by_tf` breakdown.
- 1m context = last 1m with ts ≤ entry−60 (order-independent); ATR60mean/calm/trend
  replicate `lab_mtf.py` exactly (windows inclusive of ctx bar).

## 6. Verification — backtest == lab DIGIT-FOR-DIGIT

| Check | Lab | Backtest | Match |
|---|---|---|---|
| Sniper S30a | 403 / 251 / 118 / 34 / 68.02% / 95.35R (sk=39) | same | **EXACT** |
| Volume U4 window | 4,549 / 2,562 / 1,751 / 236 / 59.40% / 426.7R (sk=341) | same | **EXACT** |
| Volume PRE Aug 11–19 | (pure-MS2 legs, MS2-validated) | 1,721 / 61.26% / +217.3R | consistent ✅ |

120s/300s re-check: volume 56.52%/53.48% (300s PF 0.977 < 1), sniper 62.08%/58.95% —
**60s expiry stays optimal** for both.

## 7. Final numbers

**MTF-Volume** full file Aug 11–Sep 10, @$10: **n=6,270, 59.91%** (CI [58.66, 61.15],
z=9.06), **+$6,440**, PF 1.27, exp +$1.08, DD $256.50, 24/27 days green (88.9%),
~232 trades/day. Legs (ALL green): FADE 2,917/58.83%/+$2,471 · SKIP 1,982/61.65%/
+$2,629 · E1B_30S 406/63.31%/+$611 · CALM_MID 459/57.37%/+$266.50 · G1M 256/59.59%/
+$251 · SKIP_CALM 160/58.94% · MONSTER 90/58.82%. TF split: 30s 662/61.79%/+$862
(accretive ✅) · 1m 5,608/59.70%. Months: Aug 59.28%/+$3,677.50 · Sep 61.04%/+$2,762.50.

vs MS2 same-file (5,707 / 59.80% / +$5,778): **+563 trades, +0.11pp WR, +$662 (+11.5%)**.

**MTF-Sniper** window Aug 20–Sep 10, @$10: **n=403, 68.02%** (CI [63.10, 72.57],
z=5.38), **+$953.50**, PF 1.808, exp +$2.58, DD **$60.00**, 14/15 days green (93.3%),
~27 trades/day, hours ONLY 21/22 UTC (= 03–05 Dhaka). TR 62.96%/+$311.50,
HO **73.33%**/+$642. h21 69.18% · h22 67.14%.

## 8. Deploy notes (read before going live)

1. The bot already supports multi-TF (`get_required_timeframes=[30,60]`); on start it
   prints `Subscribed: 30S` + `Subscribed: 1M`. **Confirm your account/asset streams
   30s candles** — if the broker doesn't send size=30, the 30s legs stay silent (1m
   legs still trade, = MS2) and the backtest numbers won't reproduce live.
2. Cold start needs ~1h of 1m history (ctx ATR60) before 30s legs arm; 1m legs arm
   after a few minutes. Leave the bot running; don't judge the first hour.
3. One strategy per account (`STRATEGY=mtf_volume` XOR `mtf_sniper`).
4. Watch-items (NO action — 27-day window can't override 365d validation): h6
   −$87.50 and h15 −$7.50 soft on this window; MS2-365d keeps both.

## 9. Journey

v1 53.7% → MS1 59.65% → MS2 60.25% (365d) → SNIPER 67.66% (WR%) →
**MTF-Volume 59.91% @ 6,270 trades (money)** + **MTF-Sniper 68.02% / HO 73.33% (WR%)**.
~230 pockets tested. Charts: `chart_mtfv.svg`, `chart_mtfs.svg`.

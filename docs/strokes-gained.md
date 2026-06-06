# Strokes Gained — methodology and what to trust

## The idea
Every position on the course has an **expected strokes to hole out** (a baseline). A
shot's SG = `E(before) − E(after) − 1`. Positive = better than the baseline's
progression; negative = worse. The sign convention is the analytics one: **+ is always
good** (you gained), − is bad (you lost). That's the opposite of "over par," so the
dashboard shows a legend.

Baseline table: `config/sg_baseline.json` — a Broadie-style **PGA-Tour (scratch)**
expected-strokes table by lie and distance (tee column recalibrated to realistic
scratch values). Interpolated linearly. Putting keys are feet; through-green keys are
yards.

## Buckets (distance-based, player-tuned)
Set by the coach's spec; cuts in `config/analysis.json` → `strokesGained`:
- **Off-the-Tee** — par 4/5 tee shots (any club)
- **Long approach** — ≥ 150 yd
- **Mid approach** — 50–150 yd
- **Inside 50** — ≤ 50 yd (the wedge/scoring zone)
- **Putting** — on the green
Par-3 tee shots fall into the distance buckets (standard). The cuts are tunable.

**SG 0–100** = the leverage metric: all non-putt shots from 100 yd and in. The single
most useful number for this player's improvement zone; it's the dashboard headline.

## Putting is count-based (a key correction)
GPS-recorded putt *shots* mismatch actual putts badly (missing real putts, phantom
putts on polluted rounds), which once produced a bogus *positive* putting stat. So
putting SG is computed from the **authoritative putt count**:
`SG_putt(hole) = expected_putts(first-putt distance) − actual putts`. Three-putts are
penalized correctly. `totalPutts` / `threePutts` are authoritative (scorecard).
Also: non-putt shots ending on the green get `E(after) = expected putts from there`,
**not** a holing credit — this removed an over-credit that flattered approach + short game.

## Penalties & doubles
Reported alongside SG, not inside the category totals. **Penalties are hole-level only
— not attributable to a specific shot** (proven: penalty holes with no off-map signal).
`offMap` (a shot ending in an unmapped lie) is the factual proxy. `doublesOrWorse` is
counted (review-first metric).

## Baselines (`progress.json` → `baselines`)
SG-vs-baseline = your SG-vs-scratch minus the baseline's:
- **Scratch** — the fixed ruler (offset 0). Everything negative is normal; good for
  long-term tracking because it never moves.
- **My average** — your all-time per-bucket average (re-centers on yourself; + = better
  than your norm).
- **Target H** — a **modeled** H-handicap: ≈H strokes/18 over scratch split by
  `handicapBucketWeights`. Documented as modeled (not empirical per-shot tables) —
  directional; the bucket ranking is the signal.

## Trust ladder (be honest)
- ✅ **Most reliable:** Off-the-Tee, Long/Mid approach — full shots, GPS good at distance.
- ✅ **Authoritative (no GPS):** putt counts, 3-putts, penalties, score-vs-rating.
- 🟡 **Count-based, believable:** putting SG (first-putt distance still GPS-noisy).
- 🟡 **GPS-approximate magnitude:** Inside-50 / short game (small distances, big relative error).
- ⚠️ **Absolute total runs a few strokes "hot"** vs score-vs-rating — trust the **ranking**,
  not the exact total. Over-recorded rounds are excluded from SG windows.

## Scoring vs Strokes Gained (two metrics, mirrored signs)
- **Score over rating** = `score − course rating` (rating = what scratch shoots, NOT par).
  Positive = worse; lower is better. Per-18 normalized so 9- and 18-hole rounds compare.
- **Strokes Gained** = vs scratch; negative = lost. Mirror image: +29 over ≈ −29 gained.
- Handicap ≈ **potential** (best ~8 of 20); SG current form ≈ **average**. The gap between
  them is volatility (blow-up tax). That's why a 23.6 handicap ≠ −23.6 SG.

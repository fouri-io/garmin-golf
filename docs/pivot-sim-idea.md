# Pivot idea — launch-monitor diagnostic coach (a future, separate product)

> Captured from a strategy conversation while building the personal `garmin-golf` app.
> This is a **fresh-product concept**, not part of this repo's roadmap. Start a new
> project when the time comes; this doc is the cold-start brief.

## One-line thesis
A subscription app + **AI coach** for **home-simulator owners** that ingests their
launch-monitor data and turns the wall of numbers (smash factor, club path, face
angle, attack angle, spin loft, carry…) into a **plain-English diagnosis + drills +
benchmarks vs. their handicap/scratch.** The thing every garage-sim golfer has the
data for but can't interpret.

## How we got here (the reasoning chain)
1. The personal app (this repo) became genuinely good → considered commercializing.
2. **Commercial wall: data access.** This app pulls Garmin golf data from *unofficial*
   reverse-engineered endpoints — fine personally, fatal commercially (ToS + rug-pull).
   Garmin's official Connect Developer Program is **fitness-only**; golf shot data is
   **not** in any public/licensed API. Building a sub business on scraped Garmin data, or
   on Arccos's subscription-locked data, is a tenant relationship that collapses.
3. "Sell to Garmin" — low-probability acquisition (they build in-house; analytics is no
   moat against the data owner). Useful only as a door-opener/demo.
4. **The unlock: home simulators.** On-course data is trapped in Garmin's cloud
   (scrubbed, GPS-only). But in a sim, the **launch monitor broadcasts shot data
   LOCALLY** into the sim software — richer (full ball/club metrics) and **accessible
   without any cloud API or scraping.** That dissolves the data-access wall.

## Why this is more defensible than the on-course play
- **The data is causal physics, not GPS guesswork.** Ball-flight laws are deterministic:
  face angle ≈ 85% of start direction; face-to-path drives curvature; smash factor =
  strike efficiency/centeredness; spin loft + attack angle drive compression/trajectory;
  low point drives fat/thin. So the **diagnostic engine can be rules + physics (reliable),
  not an LLM hallucinating** — the LLM only translates the deterministic diagnosis into a
  coach's voice.
- **Two moats:**
  1. **Encoded expertise** — the metric→pattern→root-cause→drill engine (real coaching IP,
     not an LLM wrapper).
  2. **Peer-benchmark network effect** — anonymized, consented user data becomes a
     proprietary "vs golfers your handicap" dataset that *improves with scale*. Incumbent
     apps have static stats; this compounds.

## The product
- **Buyer:** home-sim owner (garage/basement/media-room). Affluent, committed (spent
  $2K–20K on a setup), tech-comfortable, **practices alone with no coach** → the AI coach
  fills a screaming gap. Market is inflecting as LM prices crater (R10 ~$600, Garmin R50,
  SkyTrak+, FullSwing KIT, Square Golf; GSPro community booming).
- **Core value = interpretation.** Launch monitors + their apps show numbers; nobody turns
  `path −4° (out-to-in), face −1°, smash 1.31, attack −4°` into *"classic over-the-top;
  your path is your leak, face control is fine; costing ~12 yds; this week do [drill]."*
  That translation is what a $100/hr coach does with a launch monitor — productized.
- **Same shape as the current app:** data → analysis → AI coach (+ living golfer profile).
  Swap GPS Strokes Gained for launch-monitor diagnostics. The AI-coach + honesty-ethos +
  living-profile patterns carry over directly.

## Architecture sketch
```
Launch monitor (R10/Trackman/Foresight/SkyTrak…) → LOCAL feed
   │  GSPro Connect API / E6 / direct Bluetooth / LM export   ← the ingest (no Garmin cloud)
   ▼
per-shot metrics (ball speed, smash, launch, spin, club path, face, attack, dynamic/spin loft, low point, carry, dispersion)
   │  diagnostic engine = ball-flight laws + pattern detection (cluster a session, find the tendency)
   ▼
root-cause diagnosis (per club): start-line + curvature pattern, strike quality, compression, low point
   │  + benchmarks (published Trackman/Tour now; proprietary peer data later)
   ▼
AI coach → plain-English report + drills + trend, grounded in a living golfer profile
```

## Diagnosis examples (the rule set to encode)
- Low smash (driver) + off-center → strike/centeredness → "losing ball speed; center it / hit up."
- Face-to-path closed → draw/hook; open → fade/slice. + face angle (start line) → pull/push/draw/fade/slice precisely.
- Path out-to-in → over-the-top / pull-slice bias; in-to-out → push-draw bias.
- High spin loft → spinny/short → delofting/compression issue.
- Steep attack + low point behind ball (irons) → fat; thin/low point ahead → contact.

## Honest caveats (carry the app's data-honesty ethos)
1. **Device variance.** R10 *estimates* club path/face (modeled, less accurate than
   camera systems like Foresight/Trackman). The engine must hold a **per-device reliability
   map** and never diagnose a fault off a metric that device only estimates. Flag
   low-confidence metrics ("treat as directional"), exactly like the GPS caveats here.
2. **Aggregate, not single-shot.** Diagnose *patterns* across a session; never one swing.
3. **Per-club context.** "Good" ranges + benchmarks are club-specific.
4. **Benchmark sourcing.** Ball speed/smash/carry/launch/spin by club are well-published
   (Trackman/Tour). Path/face/dispersion-by-handicap are sparse — use what's published,
   flag confidence, build the rest from real (consented) user data over time. Don't fabricate.

## Validation (cheapest first proof)
- Capture one R10 range session (R10 → GSPro/E6 feed or R10 export), build the
  ball-flight-laws diagnostic on it, run the coach. Judge: is the plain-English diagnosis
  **accurate** (matches a known swing fault) and **useful**? The founder understands the
  metrics (Trackman University), so he can grade the engine's correctness directly.
- Then show the report to a handful of home-sim owners (r/Golfsimulator, GSPro community,
  local). Do their eyes light up? Would they pay ~$15/mo?

## Sequencing
- **Consumer home-sim first** (clear pain, willing payers, accessible local data, growing).
- **Coaches/sim-bays as a later expansion** (a "pro tier"; instructors teaching sim
  students). Same engine, second buyer — not the starting wedge.
- Hardware (own-capture club tracker) stays **shelved** — the launch monitor IS the
  capture device for this market, so no hardware needed. (Earlier hardware research:
  cheap commodity pucks, patent-risky, undifferentiated — see roadmap.md.)

## What carries over from this repo
- The **AI coach** (provider-agnostic Anthropic/OpenAI, living golfer profile, honesty
  guardrails) — `src/coach.py`, `config/golfer_profile.md`.
- The **data-honesty discipline** (authoritative vs estimated; flag low-confidence;
  aggregate over noisy single events; reconciliation).
- The **pipeline shape** (ingest → parse → analyze → AI report → site) and the
  self-contained static dashboard generator.
- The **Strokes Gained / baseline / trend** machinery (adapt to practice context:
  dispersion, gapping, distance control, consistency over time).

## Open questions to resolve in the new project
- Cleanest ingest per launch monitor (GSPro Connect as a hub? direct Bluetooth? per-LM SDKs?).
- Which launch monitors to support first (R10 + GSPro = biggest budget install base).
- Benchmark licensing vs. build-your-own; cold-start before the peer dataset exists.
- Sim-round vs. range-session modes (virtual course geometry from GSPro/E6 enables shot maps on virtual holes).
- Pricing / packaging (consumer sub; later pro/coach tier).

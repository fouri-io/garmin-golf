# Golfer phasing model — a developmental map (concept brief)

> Captured from a strategy/thinking conversation while building `garmin-golf`.
> This is a **mental model + product-thinking brief**, not part of the build roadmap.
> It answers: "at what point are you *golfing*?" and "what should a player at phase X
> actually track / chase / join?" Use it to make the app (and the AI coach) **meet a
> golfer where they are** instead of dumping advanced analytics on a beginner.

## The insight
Golf culture flattens a huge developmental range into one word ("golfer") and one goal
("break 90/80"). But a true beginner's job is *make it around the course without
demoralizing spirals*, while a Phase-3 player's job is *course management and distance
control*. Same sport, completely different success criteria — and completely different
things worth **tracking, practicing, and competing in**. A coach that ignores this gives
everyone the same (wrong-for-most) advice.

## Grounding: skill acquisition + social layers
Motor-skill learning has classic stages (Fitts & Posner): **cognitive** (think through
every move) → **associative** (refine through reps) → **autonomous** (it just happens).
Golf maps onto this, but stacks **social/competitive readiness** (pace of play, etiquette,
handicap, league/tournament formats) on top — and *those* gates matter as much as ball-
striking for "when is it real golf."

## The phases

| Phase | Gate (what you can do) | What "success" is | What to TRACK | When to COMPETE |
|---|---|---|---|---|
| **0 · Survival** | Can't finish solo at pace; scrambles, plays forward, picks up | Hit *some* good shots, have fun, learn pace & etiquette | Nothing numeric — maybe "good shots per outing" | Scrambles only (team hides weakness) |
| **1 · Completion** | Can get around 9→18 solo at acceptable pace, but disasters everywhere | Finish without lost-ball spirals; basic escape short game | Penalties / lost balls / whiffs — counts, not score | Casual scrambles, social leagues |
| **2 · Bogey golf** ("break 100") | Finishes, occasional pars, frequent doubles/triples. ~95–110. **The great plateau** | Kill the catastrophe holes — this *is* the break-90 journey | **Handicap now means something.** Index + penalties/doubles | Net leagues, member-guests (handicap = fair fight) |
| **3 · Consistency** ("break 90") | Reliable bogey golf, breaks 90 regularly. Index ~9–18 | Course management, distance control, real short game | **Strokes Gained becomes actionable** (this app's sweet spot) | Club net events, leagues |
| **4 · Refinement** ("break 80") | Single-digit, breaks 80 sometimes | Fine margins — wedges, putting pace, swing under pressure | Granular SG vs scratch + benchmarks, launch-monitor work | **Gross** competition, club championship |
| **5 · Mastery** (scratch+) | ~Scratch or better | Tournament performance, mental game | Course-specific prep, shot patterns, dispersion | Amateur events |

## Transition rules (the actual decisions)
- **Start a handicap at Phase 2** — once you can post legitimate 18-hole scores (with
  net-double-bogey caps). Before that, scores are too noisy/incomplete (gimmes, mulligans)
  for an index to mean anything.
- **Scrambles work at any phase** — social, low-pressure, team format hides individual
  weakness. The right on-ramp for a true beginner (or a kid).
- **Individual *net* competition: Phase 2–3** (you need the handicap). **Gross
  competition: Phase 4+.**
- **Strokes Gained earns its rent at Phase 3+.** In Phase 2 the dominant signal is just
  "stop the disasters" — penalties, doubles, three-putts — not subtle SG deltas.

## The core principle: track to the phase
The highest-leverage metric *changes* by phase. Showing a Phase-1 beginner a strokes-
gained-putting chart is noise; showing a Phase-4 player "you made a double" is useless.
Match the instrument to the stage:
- Phase 0–1: counts (penalties, lost balls) and *fun*.
- Phase 2: disaster elimination (penalties/18, doubles/18, 3-putts/18) + start the index.
- Phase 3+: Strokes Gained by category, distance control, dispersion, benchmarks.

## Population distribution (SOFT — needs sourcing before relying on it)
Caveat: golf scoring stats are unreliable (most golfers don't keep honest score —
gimmes, breakfast balls), and handicap data is biased toward the serious/better subset
who bother to carry one. Rough, commonly-cited figures:
- **~26M** US on-course golfers (NGF). Only roughly **10–15%** carry an official handicap.
- **~25% break 90** regularly; the modal golfer shoots **90–110**.
- **<5% break 80**; **~1–2% scratch or better**.
- Average handicap index (GHIN): men **~14**, women **~28** — but that's the *handicapped
  subset*, so it overstates the true population. Real center of mass = **Phase 2**.
- **TODO:** replace with sourced figures (NGF participation report; USGA/GHIN published
  handicap-index distribution) before using these anywhere real.

## Product implication: phase-aware coaching
The onboarding/coach should **detect a player's phase and meet them there**:
- Infer phase from posted scores + variance + rounds completed (and whether they finish solo).
- Give phase-appropriate guidance: "You're a Phase-2 bogey golfer — ignore SG putting
  noise; here's your disaster-elimination plan; *now's* the time to start a handicap and
  try a net league."
- Re-tier the dashboard by phase (hide advanced SG until it's actionable).
This is a far smarter first-run than dumping strokes-gained on a beginner — and it's a
natural extension of the AI-coach + living-profile pattern this app already has.

## Where the author sits (snapshot, ~10 months in)
Solidly **Phase 2** (bogey golf, est. index ~21), flirting with **Phase 3** (breaking 90).
The app is well-matched: its headline metrics (penalties/18, doubles/18, #1 leak) are
exactly the Phase-2 levers, while the SG machinery is pre-built for the Phase-3 transition.
2026 goal = solid Phase-3 entry (break 90 regularly, index into the mid-teens).

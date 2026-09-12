# vNext2 — Multi-tenant vision brief (pre-work, not yet started)

*Written 2026-09-12 at the close of the benchmark-era session, as the handoff brief for
the session that starts this refactor. Read `architecture.md` and `decisions.md` first;
this documents the intent, constraints, and recommended shape agreed with Colby before
any code.*

## Trigger & demand signal
- Steve forked The Turn and uses it for his own scores + coaching (strongest possible
  user research: someone self-served multi-tenancy by forking).
- Mike Wray (author, Caveman Golf books) is interested — a coach/author persona angle.
- Colby's intent: multi-tenant responsive site — round annotations, practice plans,
  coaching — while colbyward.io/golf keeps working throughout.

## What must survive (the moat — write these into any new spec as non-negotiables)
1. **Files as truth, DB never holds unique state.** Layered raw → canon/annot → derived.
   Loader bugs can't corrupt truth; everything downstream rebuildable.
2. **Deterministic-computes / LLM-narrates.** The coach never does arithmetic; every
   number it can quote is precomputed, labeled, and source-cited.
3. **Scorecard is truth** (ADR #3 hierarchy); context never alters SG (ADR #17).
4. **The interpretability bar** (see memory): plain-word labels, one scope per line,
   every headline number answerable "was it good?" at a glance. ~10 of Colby's sniff
   tests forged these; multi-tenant convenience must not erode them.
5. **Scoping rules:** scoring-level units = 18-hole regulation rounds only; rates/SG =
   all rounds; rating-level scores before ANY population comparison (a raw average off
   easy tees flatters the player — the Broadie bracket bug).

## Recommended tenancy architecture
- **Tenancy = a file prefix, not a schema change.** `users/<id>/{raw,annotations,config,
  processed}` on object storage; **one DuckDB per tenant**, still gitignored-class
  (rebuildable, disposable). Do NOT move golf data into a shared Postgres — that trades
  the rebuildability moat for scale that 3–50 users don't need.
- **Postgres (or similar) as control plane only:** accounts, sessions, job queue,
  billing/cost caps, sharing grants. This is the ADR-anticipated "multi-tenant →
  Postgres" line, scoped correctly.
- **Pipeline stays a per-tenant batch job** (ingest → derive → export → coach → site
  data). Thin web layer over generated artifacts; do not rewrite the pipeline into a
  web framework.
- **Site:** per-user generated static JSON + one shared responsive app shell + auth in
  front, evolving from (not discarding) the current generator. The single-file
  inlined-data PWA remains the single-tenant mode.

## Connector architecture (Colby's correction, 2026-09-12 — supersedes "Garmin
## acquisition is the existential risk")
The canonical layer already killed the Garmin dependency: Steve runs The Turn on data
pulled directly from 18Birdies (less rich, fully operational). Data acquisition is a
**connector model**, home-grown or first-class, all writing raw snapshots into the
tenant's prefix:
- **Garmin edge agent** — Colby's mac mini keeps pulling (home IP; rate limits and
  creds stay at the user's edge), but its only job becomes uploading raw JSON to
  `s3://<bucket>/users/<id>/raw/` (a per-user raw/snapshot inbox meant for processing).
- **18Birdies connector** — Steve's path; second first-class connector.
- **Manual upload** — universal fallback (the 18Birdies screenshot backfill + validator
  is the working prototype). Product works with zero integrations.
Rule stands: NEVER take custody of other users' source credentials server-side —
connectors that need creds run at the user's edge.

## Target runtime (decided: AWS, serverless, nearly-static)
- **Compute:** "Generate" = a pipeline Lambda (container image — duckdb wheel) running
  ingest → derive → export → per-user site JSON. Data is tiny; a full rebuild is
  seconds. Triggers: S3 event on the tenant's raw/annotations prefix, or an
  authenticated button invoke. The mac mini stops being the orchestrator.
- **Write path without abandoning static:** annotation web form on the static site
  POSTs to a Lambda Function URL / API Gateway that validates and writes the narrative
  file to the tenant prefix — files-as-truth preserved; ~two Lambdas total
  (submit-annotation, generate) is the whole dynamic surface at first.
- **Durability:** per-tenant data moves from git to a VERSIONED S3 bucket — same
  immutable-audit property, right tool for multi-tenant. (This repo's git history
  remains the story for Colby's own data until migration.)
- **Read path:** per-user generated JSON + shared responsive app shell behind
  CloudFront with auth (Cognito or similar; signed cookies for per-user artifacts).
- **Mobile: PWA first, Capacitor wrap when accounts exist.** Phase B's app shell ships
  as a proper PWA (manifest + service worker; installable, iOS push works since 16.4) —
  zero store friction for Steve/Mike-scale testing. App Store presence = wrap the same
  web app in Capacitor once auth exists (Apple guideline 4.2 needs it to be app-like:
  offline support, push for "round processed / coach report ready", Sign in with
  Apple). Design the shell for this from day one: same generated artifacts serve web,
  PWA, and the native shell — the App Store is a packaging decision, not an
  architecture one. Native (SwiftUI/RN) only if on-course use, Watch, or HealthKit
  later earn it. Keep billing on the web; the app is a client.

## Positioning (vs Arccos / Shot Scope — agreed 2026-09-13)
They are measurement products (hardware capture, huge population benchmarks, polish);
do not compete on measurement. The Turn is a longitudinal coaching system, and the
moat is what their architecture can't copy: (1) a coach with memory + accountability
(course memory, prescription grading, the adherence loop); (2) the player's own words
as first-class data (intent-aware stats sensors can't have); (3) interpretability as a
product value (honest scoping, rating-leveling, cited benchmarks); (4) source-agnostic,
no hardware tax (the connector model — Steve onboarded with what he already had).
One-liner: they tell you what happened; The Turn remembers who you are, tells you why
it happened, and checks whether you did the work.

## Remaining hard problems (analytics still not on the list)
1. **Auth on a static-first product** (see target runtime above).
2. **LLM cost + coach identity.** Coach prompt is currently Colby-tuned (priorities,
   pronouns, Q-plan). `golfer_profile.md` becomes each tenant's editable living spec
   driving personalization — that IS the flagship feature for Steve/Mike. Per-user cost
   controls and key ownership from day one; the coach Lambda is the metering point.
3. **Annotation UX.** Web-form → file (above). Practice plans = the generalization of
   the existing focus-card adherence loop (focus.json → graded next report → rendered
   card).
4. **Connector richness tiers.** Canon must degrade gracefully by source richness
   (Garmin: shot-level GPS; 18Birdies: hole-level) — coverage badges and metric
   availability per source are already the house pattern; formalize per-connector
   capability flags.

## Phasing
- **A — multi-user before multi-tenant (pure refactor, no product risk):** parametrize
  the whole pipeline on a user root; extract every Colby-specific constant into
  per-user config (profile, clubs, courses, keys, publish target). Verification: two
  local users (Colby + a fixture user, ideally Steve's fork data) run side by side,
  byte-identical outputs for Colby vs today.
- **B — hosted read:** auth + per-user dashboards from generated JSON; ingest still at
  the user's edge or via upload.
- **C — hosted write:** in-app annotations + practice plans (file-backed), job runner,
  coach runs with billing caps.
- **D — product proper:** control plane, Garmin strategy decision executed, sharing
  (coach-views-player: the Mike Wray angle — an author's methodology as a coach
  persona), onboarding.

## Do-not list
- Don't break or freeze colbyward.io/golf — it is the daily tool and the reference
  implementation; vNext2 is built beside it.
- Don't move golf data into a shared relational schema.
- Don't rewrite the pipeline into a framework.
- Don't store third-party Garmin credentials server-side.
- Don't let per-tenant customization fork the analytics definitions (one SG model, one
  cone definition, one benchmark config — tenant config selects targets, not math).

## Answered at pre-kickoff (2026-09-12)
- ~~Garmin strategy~~ → connector model; Garmin = edge agent uploading to S3; 18Birdies
  proven by Steve; manual upload as fallback. Not a limiting factor.
- ~~Hosting~~ → AWS, serverless/nearly-static: pipeline Lambda + form-to-file Lambda;
  mac mini demoted to a connector.

## Open questions for Colby (answer at vNext2 kickoff)
1. Is Steve a design partner (his fork = migration test case #1, and his 18Birdies
   puller = candidate first-class connector)?
2. Business posture: free for friends, or billing from the start (affects LLM cost
   design and auth choice)?
3. Practice plans: what does one look like on paper today? (Get a real example before
   designing the feature.)
4. Auth provider preference (Cognito vs a third party like Clerk/Auth0) — the one
   remaining runtime choice that shapes Phase B.

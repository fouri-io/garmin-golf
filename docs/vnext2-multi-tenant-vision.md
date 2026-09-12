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

## The four hard problems (ranked — the analytics are NOT on this list)
1. **Garmin acquisition.** Unofficial API: rate-limits datacenter IPs (pull-at-home is a
   documented constraint), needs per-user credentials + MFA, and hosting it for others
   is a different ToS/liability posture than personal use. NEVER take custody of other
   users' Garmin passwords. Options: per-user edge/home puller agent; manual upload
   (the 18Birdies screenshot backfill + validator is a working prototype of this);
   official Garmin developer program (approval, limited golf endpoints). Decide this
   FIRST; design manual upload as the universal fallback so the product works with zero
   integrations.
2. **Auth on a static-first product** (see architecture above).
3. **LLM cost + coach identity.** Coach prompt is currently Colby-tuned (priorities,
   pronouns, Q-plan). `golfer_profile.md` becomes each tenant's editable living spec
   driving personalization — that IS the flagship feature for Steve/Mike. Per-user cost
   controls and key ownership from day one.
4. **Annotation UX.** Move in-app but keep file-backed (web form writes the narrative
   file to the tenant prefix — files-as-truth preserved). Practice plans = the
   generalization of the existing focus-card adherence loop (focus.json → graded next
   report → rendered card).

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

## Open questions for Colby (answer at vNext2 kickoff)
1. Garmin strategy: edge agent vs manual upload vs official program — which first?
2. Hosting/runtime preference (stay AWS/S3+CloudFront? add a small server? serverless?)
3. Is Steve a design partner (his fork = migration test case #1)?
4. Business posture: free for friends, or billing from the start (affects LLM cost
   design and auth choice)?
5. Practice plans: what does one look like on paper today? (Get a real example before
   designing the feature.)

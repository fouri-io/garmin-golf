# Key decisions (and why)

Short ADR-style log of choices that aren't obvious from the code.

1. **Raw saved before parsing.** Garmin endpoints are unofficial and breakable; raw is
   the asset, parsing is disposable. A server-side change can never cost retrieved data.

2. **Round document = faithful superset.** Preserve every Garmin field; add derived
   fields alongside with provenance. Lets a consumer always tell Garmin-truth from our
   inference; never lose information.

3. **Score is authoritative; shots are spatial detail.** They don't reconcile exactly
   (sensor over/under-records). We surface the gap (`reconciliation`) rather than force
   agreement. Never "correct" the score to match shot count.

4. **Club identity by physical `clubId`, not `clubTypeId`.** Garmin's type is coarse and
   merged the wedges; clubId keeps 50/54/58 separate. Retired clubs excluded.

5. **Analysis cutoff (2026-05-01) + SIM exclusion.** Pre-cutoff rounds used different
   clubs/no sensors, so the club map and SG don't apply; simulator rounds aren't real golf.

6. **Distance-based SG buckets (Long/Mid/Inside-50), not the PGA OTT/APP/ARG.** Tuned to
   how this player thinks (the ≤90→≤50 wedge "scoring zone" is his focus). Cuts are
   configurable. A standard-categories toggle is a future add for app comparability.

7. **SG 0–100 is the headline metric.** Per the coach: the single highest-leverage number
   for a mid-90s→80s player; it's the dashboard's lead.

8. **Putting SG is count-based, not GPS shot-based.** GPS putt shots mismatch reality
   (missing/phantom) and once produced a false positive putting stat. Count-based
   (`expected_putts(first-putt) − actual putts`) penalizes 3-putts correctly.

9. **Scratch is the fixed ruler; baselines are layered on.** A fixed baseline makes
   trends comparable across months/years. "My average" and "Target H" are offsets from
   scratch (data-driven / modeled), not separate rulers.

10. **Target handicap baseline is MODELED, labeled as such.** No empirical per-handicap
    tables, so we model it (≈H over scratch, split by weights). Directional; never faked
    as measured.

11. **Score-over-rating uses course rating, not par.** Rating = what scratch shoots;
    accounts for tee/course difficulty so skill compares fairly. Per-18 normalized.

12. **Single self-contained HTML site, data inlined.** No fetch/CORS, works from
    `file://`, trivially hostable on S3. Leaflet/CDN only for maps (online-only part).

13. **Hardware is not the play (researched, shelved).** Grip sensors are cheap commodity;
    the moat is the analytics + the $200/yr subscription incumbents charge — which this
    project already replaces. If ever commercialized: hardware-agnostic analytics/coaching,
    not another sensor (patent-risky, undifferentiated). See roadmap.md.

14. **AI coach uses the Anthropic API + a living golfer spec.** Key in `.env`
    (`ANTHROPIC_API_KEY`); degrades gracefully if absent. The living spec
    (`config/golfer_profile.md` + auto-generated state) is the durable context that makes
    coaching personal. See coach.md.

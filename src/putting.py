"""Putting, treated as a first-class citizen — authoritative counts, by distance.

Buckets each hole's first putt by its (GPS-estimated) distance and summarizes the
ACTUAL putt counts in that bucket: how many first putts, the average putts to hole
out, and the make rate (1-putts). This is intentionally separate from Strokes
Gained — it does not model expected putts or compare to scratch. Putt *counts* are
authoritative (from the scorecard); first-putt *distance* is GPS-derived, so the
shortest bucket is the least reliable (flagged in the UI).

Used by both progress.py (Overview, aggregated over a window) and site.py (per
round) so the two views always bucket identically.
"""

from __future__ import annotations

# (label, low_ft_inclusive, high_ft_exclusive)
PUTT_BUCKETS = [
    ("0–10 ft", 0.0, 10.0),
    ("10–20 ft", 10.0, 20.0),
    ("20–30 ft", 20.0, 30.0),
    ("30–50 ft", 30.0, 50.0),
    ("50+ ft", 50.0, float("inf")),
]


def putt_buckets(holes: list[dict]) -> list[dict]:
    """Summarize authoritative putt counts by first-putt distance bucket.

    Each returned bucket: {label, n, avg, makePct} where n = first putts in the
    bucket, avg = mean putts to hole out (None if empty), makePct = % holed in one.
    Holes with no recorded putts or no first-putt distance are skipped.
    """
    out = [{"label": lab, "_lo": lo, "_hi": hi, "n": 0, "_putts": 0, "_makes": 0}
           for lab, lo, hi in PUTT_BUCKETS]
    for h in holes:
        fp = h.get("firstPuttDistanceFt")
        p = h.get("putts")
        if fp is None or not p:
            continue
        for b in out:
            if b["_lo"] <= fp < b["_hi"]:
                b["n"] += 1
                b["_putts"] += p
                b["_makes"] += 1 if p == 1 else 0
                break
    for b in out:
        n = b["n"]
        b["avg"] = round(b["_putts"] / n, 2) if n else None
        b["makePct"] = round(100 * b["_makes"] / n) if n else None
        for k in ("_lo", "_hi", "_putts", "_makes"):
            del b[k]
    return out

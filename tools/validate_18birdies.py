"""Consistency gate for 18Birdies screenshot transcriptions.

Each transcription file carries the totals row from the screenshot; this checks that
the per-hole values sum to them (nullable columns must sum to <= the total, and match
exactly when no holes are null). Run after adding or editing transcriptions:

    python -m tools.validate_18birdies
"""

from __future__ import annotations

import json
from pathlib import Path

DIR = Path("data/raw/18birdies")


def check() -> list[str]:
    problems = []
    files = sorted(DIR.glob("*.json"))
    for f in files:
        d = json.loads(f.read_text())
        holes, totals = d["holes"], d["totals"]
        name = f.name

        if len(holes) != d["holesPlayed"]:
            problems.append(f"{name}: {len(holes)} holes vs holesPlayed {d['holesPlayed']}")
        if [h["hole"] for h in holes] != list(range(1, d["holesPlayed"] + 1)):
            problems.append(f"{name}: hole numbers not 1..{d['holesPlayed']}")

        def col(key):
            return [h[key] for h in holes]

        # score: never null, must match exactly
        if any(v is None for v in col("score")):
            problems.append(f"{name}: null score cell")
        elif sum(col("score")) != totals["score"]:
            problems.append(f"{name}: score sum {sum(col('score'))} != TOT {totals['score']}")

        # nullable numeric columns: non-null sum must equal the stated total
        for key, tkey in (("putts", "putts"), ("penalties", "penalties")):
            if totals.get(tkey) is None:
                continue
            vals = [v for v in col(key) if v is not None]
            if sum(vals) != totals[tkey]:
                problems.append(f"{name}: {key} sum {sum(vals)} != TOT {totals[tkey]}")

        # marks: count of positives must equal the stated total
        fw_hits = sum(1 for v in col("fairway") if v == "HIT")
        if totals.get("fairwaysHit") is not None and fw_hits != totals["fairwaysHit"]:
            problems.append(f"{name}: fairway HITs {fw_hits} != TOT {totals['fairwaysHit']}")
        girs = sum(1 for v in col("gir") if v is True)
        if totals.get("gir") is not None and girs != totals["gir"]:
            problems.append(f"{name}: GIR count {girs} != TOT {totals['gir']}")

        # par sanity: no golf hole is par <3 or >5; score within plausible bounds
        for h in holes:
            if not 3 <= h["par"] <= 5:
                problems.append(f"{name} H{h['hole']}: implausible par {h['par']}")
            if h["score"] is not None and not 1 <= h["score"] <= 12:
                problems.append(f"{name} H{h['hole']}: implausible score {h['score']}")
            if h["putts"] is not None and h["score"] is not None and h["putts"] >= h["score"]:
                problems.append(f"{name} H{h['hole']}: putts {h['putts']} >= score {h['score']}")

    print(f"18birdies transcriptions: {len(files)} files, {len(problems)} problems")
    for p in problems:
        print("  " + p)
    return problems


if __name__ == "__main__":
    raise SystemExit(1 if check() else 0)

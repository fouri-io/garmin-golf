"""Task 1 — library introspection.

Discover the golf method names and signatures in the *installed* garminconnect
version rather than assuming them. This needs NO credentials and makes NO network
calls — it only inspects the class.

Run:  python -m src.introspect
"""

from __future__ import annotations

import inspect

from garminconnect import Garmin


def candidate_golf_methods() -> list[str]:
    return sorted(
        name
        for name in dir(Garmin)
        if not name.startswith("_")
        and ("golf" in name.lower() or "scorecard" in name.lower())
    )


def main() -> None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        ver = version("garminconnect")
    except PackageNotFoundError:
        ver = "unknown"
    print(f"garminconnect version: {ver}\n")

    methods = candidate_golf_methods()
    if not methods:
        print("No 'golf'/'scorecard' methods found on Garmin. Dumping all public methods:")
        methods = sorted(n for n in dir(Garmin) if not n.startswith("_"))

    print(f"Candidate golf methods ({len(methods)}):\n")
    for name in methods:
        attr = getattr(Garmin, name)
        if callable(attr):
            try:
                sig = str(inspect.signature(attr))
            except (TypeError, ValueError):
                sig = "(?)"
            doc = (inspect.getdoc(attr) or "").splitlines()
            summary = doc[0] if doc else ""
            print(f"  {name}{sig}")
            if summary:
                print(f"      {summary}")


if __name__ == "__main__":
    main()

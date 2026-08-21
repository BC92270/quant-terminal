#!/usr/bin/env python3
"""Report provider coverage without reading, printing or persisting key values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from provider_config import configured_provider_keys, provider_matrix  # noqa: E402


def build_report() -> dict[str, object]:
    configured = configured_provider_keys()
    sections: list[dict[str, object]] = []
    for row in provider_matrix():
        names = [name.strip() for name in str(row["optional_keys"]).split(",") if name.strip() and name != "None"]
        sections.append(
            {
                **row,
                "configured_keys": [name for name in names if configured.get(name, False)],
                "missing_optional_keys": [name for name in names if not configured.get(name, False)],
            }
        )
    return {
        "summary": {
            "sections": len(sections),
            "known_optional_keys": len(configured),
            "configured_optional_keys": sum(configured.values()),
        },
        "keys": configured,
        "sections": sections,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    summary = report["summary"]
    print(
        "Provider audit: "
        f"{summary['configured_optional_keys']}/{summary['known_optional_keys']} optional keys configured "
        f"across {summary['sections']} sections."
    )
    for section in report["sections"]:
        ready = section["configured_keys"]
        missing = section["missing_optional_keys"]
        state = "KEYLESS/FALLBACK READY" if not ready else "CONFIGURED"
        print(f"\n[{state}] {section['section']}")
        print(f"  Primary: {section['primary']}")
        print(f"  Fallback: {section['keyless_or_local_fallback']}")
        print(f"  Configured keys: {', '.join(ready) if ready else 'none'}")
        print(f"  Missing optional: {', '.join(missing) if missing else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

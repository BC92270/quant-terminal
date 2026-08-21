#!/usr/bin/env python3
"""Refresh provider-backed security-master reference records."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from security_master import (
    SecurityMasterStore,
    sync_nasdaq_symbol_directory,
    sync_sec_company_tickers,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".quant_data/security_master.sqlite3", help="SQLite cache path")
    parser.add_argument(
        "--provider",
        choices=("all", "nasdaq_directory", "sec_edgar"),
        default="all",
    )
    args = parser.parse_args()

    store = SecurityMasterStore(args.db)
    results = []
    if args.provider in {"all", "nasdaq_directory"}:
        results.append(sync_nasdaq_symbol_directory(store))
    if args.provider in {"all", "sec_edgar"}:
        results.append(sync_sec_company_tickers(store))
    print(
        json.dumps(
            {"sync": [asdict(result) for result in results], "health": store.health()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if any(result.status == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

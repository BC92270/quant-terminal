#!/usr/bin/env python3
"""Fetch one recent official World Bank observation per economy and indicator."""

from __future__ import annotations

import gzip
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


INDICATORS = [
    "SP.POP.TOTL", "NY.GDP.MKTP.CD", "NY.GDP.PCAP.CD", "NY.GDP.MKTP.KD.ZG",
    "FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS", "NE.TRD.GNFS.ZS", "NE.IMP.GNFS.ZS",
    "BX.KLT.DINV.WD.GD.ZS", "GC.DOD.TOTL.GD.ZS", "DT.DOD.DECT.CD",
    "FI.RES.TOTL.CD", "EG.IMP.CONS.ZS", "EG.ELC.ACCS.ZS", "IT.NET.USER.ZS",
    "SP.URB.TOTL.IN.ZS", "MS.MIL.XPND.GD.ZS", "NV.AGR.TOTL.ZS", "ER.H2O.FWTL.ZS",
]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "worldmonitor" / "data" / "world_bank_wdi.json.gz"


def fetch(code: str) -> tuple[str, dict]:
    query = urllib.parse.urlencode({
        "format": "json", "mrv": 1, "gapfill": "Y", "per_page": 400,
    })
    url = f"https://api.worldbank.org/v2/country/all/indicator/{code}?{query}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "QuantTerminal-WorldMonitor/8"})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
                raise RuntimeError(f"unexpected World Bank response for {code}")
            meta = payload[0] if isinstance(payload[0], dict) else {}
            records: dict[str, dict] = {}
            for row in payload[1]:
                if not isinstance(row, dict) or row.get("value") is None:
                    continue
                iso3 = str(row.get("countryiso3code") or "").upper()
                if len(iso3) != 3:
                    continue
                records[iso3] = {
                    "value": row.get("value"),
                    "date": row.get("date"),
                    "indicator": str((row.get("indicator") or {}).get("value") or code),
                    "unit": row.get("unit") or "",
                    "source": "World Bank World Development Indicators",
                    "source_id": str(meta.get("sourceid") or "2"),
                    "source_updated": meta.get("lastupdated"),
                }
            return code, {"records": records, "last_updated": meta.get("lastupdated"), "url": url}
        except Exception as exc:  # pragma: no cover - exercised by build environment
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{code}: {last_error}")


def main() -> None:
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="world-bank") as pool:
        futures = {pool.submit(fetch, code): code for code in INDICATORS}
        for future in as_completed(futures):
            code = futures[future]
            try:
                returned_code, payload = future.result()
                results[returned_code] = payload
            except Exception as exc:
                errors[code] = str(exc)
    if len(results) < 12:
        raise RuntimeError(f"World Bank snapshot incomplete: {len(results)}/{len(INDICATORS)}; {errors}")
    output = {
        "schema_version": 1,
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "license_note": "World Bank data; attribution retained per indicator.",
        "indicators": {code: results[code] for code in sorted(results)},
        "errors": errors,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    countries = {iso for item in results.values() for iso in item["records"]}
    print(json.dumps({"output": str(OUTPUT), "indicators": len(results), "economies": len(countries), "errors": errors}, indent=2))


if __name__ == "__main__":
    main()


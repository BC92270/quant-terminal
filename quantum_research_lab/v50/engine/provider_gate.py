"""Hard provider boundary for V5.0.

This module intentionally has no provider-SDK import, credential lookup,
network client, sampler, estimator, session, simulator, or backend execution
path.  It can only expose the authenticated offline decision and reject access.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .checker import validate_artifact
from .evaluator import ARTIFACT, default_root
from .evidence import raw_file_sha256, read_json_strict


class ProviderGateClosed(RuntimeError):
    """Raised before any provider or credential interaction can occur."""


def authenticated_status(root: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    artifact_path = project_root / ARTIFACT
    artifact = read_json_strict(artifact_path)
    integrity = validate_artifact(
        artifact,
        root=project_root,
        artifact_raw_sha256=raw_file_sha256(artifact_path),
    )
    if integrity.get("valid") is not True:
        raise ProviderGateClosed("V5.0 artifact authentication failed; provider gate is closed")
    decisions = artifact["decisions"]
    return {
        "authenticated": True,
        "scientific_decision": decisions["overall"],
        "historical_epoch_gate": decisions["historical_epoch_gate"],
        "architecture_gate": decisions["architecture_gate"],
        "current_provider_discovery": decisions["current_provider_discovery"],
        "v5_execution": decisions["v5_execution"],
        "hardware_executable": False,
        "provider_calls": 0,
        "network_calls": 0,
        "qpu_jobs_submitted": 0,
    }


def require_provider_access(root: str | Path | None = None) -> None:
    status = authenticated_status(root)
    raise ProviderGateClosed(
        "Provider access denied before SDK import or credential read: "
        f"{status['scientific_decision']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--status", action="store_true", help="Print the offline gate state")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(authenticated_status(args.root), indent=2, sort_keys=True))
        return 0
    require_provider_access(args.root)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

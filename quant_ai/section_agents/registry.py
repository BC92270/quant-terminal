"""Registry for independently configured section assistants."""

from __future__ import annotations

from collections.abc import Iterable
import re
import unicodedata

from .contracts import SectionManifest
from .manifests import NAVIGATOR_MANIFEST, TRADING_PLAN_MANIFEST, WORKSPACE_MANIFESTS


class SectionAgentRegistry:
    def __init__(self, manifests: Iterable[SectionManifest] = ()) -> None:
        self._manifests: dict[str, SectionManifest] = {}
        self._aliases: dict[str, str] = {}
        for manifest in manifests:
            self.register(manifest)

    def register(self, manifest: SectionManifest, *, replace: bool = False) -> "SectionAgentRegistry":
        section_id = manifest.section_id.strip().lower()
        if not section_id:
            raise ValueError("Section manifests require a non-empty section_id.")
        if section_id != manifest.section_id:
            raise ValueError("section_id must already be normalized to lowercase.")
        if section_id in self._manifests and not replace:
            raise ValueError(f"Section assistant already registered: {section_id}")
        if len(set(manifest.allowed_tools)) != len(manifest.allowed_tools):
            raise ValueError(f"Duplicate allowed tool in manifest: {section_id}")
        self._manifests[section_id] = manifest
        for value in (
            manifest.section_id,
            manifest.function,
            manifest.label,
            manifest.mode or "",
            manifest.special_route or "",
        ):
            alias = _normalize_alias(value)
            if alias:
                self._aliases.setdefault(alias, section_id)
        if section_id == "decision":
            self._aliases["decision_engine_lite"] = section_id
        elif section_id == "navigator":
            self._aliases["institutional_navigator"] = section_id
        return self

    def get(self, section_id: str) -> SectionManifest | None:
        resolved = self.resolve_section_id(section_id)
        return self._manifests.get(resolved) if resolved else None

    def resolve_section_id(self, value: str) -> str | None:
        normalized = _normalize_alias(value)
        if normalized in self._manifests:
            return normalized
        return self._aliases.get(normalized)

    def require(self, section_id: str) -> SectionManifest:
        manifest = self.get(section_id)
        if manifest is None:
            raise KeyError(f"Unknown section assistant: {section_id}")
        return manifest

    def codes(self) -> tuple[str, ...]:
        return tuple(self._manifests)

    def manifests(self) -> tuple[SectionManifest, ...]:
        return tuple(self._manifests.values())

    def __contains__(self, section_id: object) -> bool:
        return isinstance(section_id, str) and self.get(section_id) is not None

    def __len__(self) -> int:
        return len(self._manifests)


def build_default_section_registry(
    *,
    include_navigator: bool = True,
    include_trading_plan: bool = True,
) -> SectionAgentRegistry:
    manifests: list[SectionManifest] = list(WORKSPACE_MANIFESTS.values())
    if include_navigator:
        manifests.append(NAVIGATOR_MANIFEST)
    if include_trading_plan:
        manifests.append(TRADING_PLAN_MANIFEST)
    return SectionAgentRegistry(manifests)


def resolve_section_id(value: str) -> str | None:
    """Resolve a Navigator code, display label, legacy mode or special route."""

    return build_default_section_registry().resolve_section_id(value)


def _normalize_alias(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.casefold()).strip("_")

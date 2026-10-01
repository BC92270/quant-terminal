"""Fail-closed RESEARCH_ONLY policy for section assistants."""

from __future__ import annotations

import re
import unicodedata

from .contracts import (
    GovernanceMode,
    PolicyDecision,
    SectionAgentRequest,
    SectionManifest,
    SectionResponseDraft,
    ToolRiskLevel,
)


_FORBIDDEN_REQUEST_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(execute|submit|place|send)\s+(the\s+|an?\s+)?(trade|order)\b", "submit_order"),
    (r"\b(executer|execute|passer|passe|transmettre|transmets|envoyer|envoie)\s+(un\s+|l[' ]?)?(ordre|trade)\b", "submit_order"),
    (r"\b(allocate|deploy|invest)\s+(capital|cash|money|funds)\b", "allocate_capital"),
    (r"\b(allouer|deployer|investir)\s+(du\s+|le\s+|mon\s+)?(capital|cash|argent|fonds)\b", "allocate_capital"),
    (r"\b(change|raise|lower|override)\s+(the\s+)?risk\s+limit", "modify_risk_limit"),
    (r"\b(modifier|augmenter|baisser|contourner)\s+(la\s+|le\s+)?limite\s+de\s+risque", "modify_risk_limit"),
    (r"\b(promote|deploy)\s+(the\s+)?model\s+(to|into)\s+(production|live)", "promote_model"),
    (r"\b(promouvoir|deployer)\s+(le\s+)?modele\s+(en\s+)?(production|live)", "promote_model"),
    (r"\b(show|reveal|print|export|give)\s+(the\s+|me\s+)?(api\s+key|password|secret|credential|token)\b", "access_credentials"),
    (r"\b(afficher|reveler|imprimer|exporter|donner)\s+(la\s+|le\s+|les\s+)?(cle\s+api|mot\s+de\s+passe|secret|identifiant|token)", "access_credentials"),
)


_FORBIDDEN_RESPONSE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(place|submit|execute)\s+the\s+(trade|order)\b", "submit_order"),
    (r"\b(passez|executez|transmettez)\s+(maintenant\s+)?(cet\s+|l[' ]?)?(ordre|trade)\b", "submit_order"),
    (r"\b(buy|sell)\s+now\b", "submit_order"),
    (r"\b(achetez|vendez)\s+maintenant\b", "submit_order"),
    (r"\b(allocate|deploy)\s+\d+(?:\.\d+)?\s*%", "allocate_capital"),
    (r"\b(allouez|deployez)\s+\d+(?:[,.]\d+)?\s*%", "allocate_capital"),
    (r"\b(the\s+)?risk\s+limit\s+(is|has\s+been)\s+(changed|overridden)", "modify_risk_limit"),
    (r"\bmodel\s+(is|has\s+been)\s+promoted\s+to\s+(production|live)", "promote_model"),
)


def _normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def _find_capability(text: str, patterns: tuple[tuple[str, str], ...]) -> str | None:
    normalized = _normalized(text)
    for pattern, capability in patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return capability
    return None


class SectionPolicy:
    """Small deterministic policy layer that cannot be overridden by a model."""

    governance_mode = GovernanceMode.RESEARCH_ONLY

    def evaluate_request(self, request: SectionAgentRequest, manifest: SectionManifest) -> PolicyDecision:
        context_mode = request.context.governance_mode
        if context_mode != GovernanceMode.RESEARCH_ONLY and context_mode != GovernanceMode.RESEARCH_ONLY.value:
            return self._blocked("GOVERNANCE_MODE_DENIED", "Only RESEARCH_ONLY context is accepted.", manifest)
        if request.section_id != request.context.section_id:
            return self._blocked("SECTION_CONTEXT_MISMATCH", "Request and context section identifiers do not match.", manifest)
        capability = _find_capability(request.message, _FORBIDDEN_REQUEST_PATTERNS)
        if capability:
            return self._blocked(
                "FINANCIAL_ACTION_DENIED",
                f"{capability} is outside the research-only assistant boundary.",
                manifest,
            )
        return PolicyDecision(
            allowed=True,
            code="RESEARCH_ONLY_ALLOWED",
            reason="Advisory research and navigation are allowed; financial actions remain disabled.",
            blocked_capabilities=manifest.denied_capabilities,
        )

    def authorize_tool(
        self,
        manifest: SectionManifest,
        tool_name: str,
        risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY,
    ) -> PolicyDecision:
        if tool_name not in manifest.allowed_tools:
            return self._blocked("TOOL_NOT_ALLOWLISTED", f"Tool is not allowlisted for {manifest.section_id}: {tool_name}", manifest)
        if risk_level != ToolRiskLevel.READ_ONLY:
            return self._blocked("TOOL_RISK_DENIED", f"Tool risk level is disabled in the research-only backend: {risk_level}", manifest)
        return PolicyDecision(
            allowed=True,
            code="READ_ONLY_TOOL_ALLOWED",
            reason=f"Read-only tool is allowlisted for {manifest.section_id}.",
            blocked_capabilities=manifest.denied_capabilities,
        )

    def evaluate_draft(self, draft: SectionResponseDraft, manifest: SectionManifest) -> PolicyDecision:
        capability = _find_capability(draft.answer_markdown, _FORBIDDEN_RESPONSE_PATTERNS)
        if capability:
            return self._blocked(
                "UNSAFE_RESPONSE_DENIED",
                f"Generated response crossed the research-only boundary: {capability}.",
                manifest,
            )
        for action in draft.suggested_actions:
            if action.risk_level not in {ToolRiskLevel.READ_ONLY, ToolRiskLevel.UI_NAVIGATION}:
                return self._blocked(
                    "UNSAFE_ACTION_DENIED",
                    f"Suggested action is not read-only: {action.action_id}.",
                    manifest,
                )
        return PolicyDecision(
            allowed=True,
            code="RESEARCH_ONLY_RESPONSE_ALLOWED",
            reason="Response remains advisory and contains no authorized financial mutation.",
            blocked_capabilities=manifest.denied_capabilities,
        )

    @staticmethod
    def _blocked(code: str, reason: str, manifest: SectionManifest) -> PolicyDecision:
        return PolicyDecision(
            allowed=False,
            code=code,
            reason=reason,
            blocked_capabilities=manifest.denied_capabilities,
        )

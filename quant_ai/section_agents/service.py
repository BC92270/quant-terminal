"""Synchronous, fail-closed orchestration for one section-assistant turn."""

from __future__ import annotations

import hashlib
import time
from typing import Protocol
from uuid import uuid4

from .adapters import DeterministicSectionAdapter
from .audit import SectionAuditStore
from .contracts import (
    EvidenceGrade,
    PolicyDecision,
    ResponseStatus,
    SectionAgentRequest,
    SectionAgentResponse,
    SectionAuditRecord,
    SectionManifest,
    SectionResponseDraft,
)
from .policy import SectionPolicy
from .registry import SectionAgentRegistry, build_default_section_registry


class SectionResponseAdapter(Protocol):
    provider: str
    model: str

    def answer(
        self,
        request: SectionAgentRequest,
        manifest: SectionManifest,
    ) -> SectionResponseDraft: ...


class SectionAgentService:
    def __init__(
        self,
        *,
        registry: SectionAgentRegistry | None = None,
        policy: SectionPolicy | None = None,
        adapter: SectionResponseAdapter | None = None,
        fallback_adapter: SectionResponseAdapter | None = None,
        audit_store: SectionAuditStore | None = None,
    ) -> None:
        self.registry = registry or build_default_section_registry()
        self.policy = policy or SectionPolicy()
        self.adapter = adapter or DeterministicSectionAdapter()
        self.fallback_adapter = fallback_adapter or DeterministicSectionAdapter()
        self.audit_store = audit_store if audit_store is not None else SectionAuditStore()
        self._responses: dict[str, SectionAgentResponse] = {}

    def answer(self, request: SectionAgentRequest) -> SectionAgentResponse:
        started = time.perf_counter()
        request_id = request.effective_request_id or uuid4().hex
        if request_id in self._responses:
            return self._responses[request_id]

        manifest = self.registry.require(request.section_id)
        decision = self.policy.evaluate_request(request, manifest)
        if not decision.allowed:
            response = self._blocked_response(request, decision, started)
            return self._remember_and_audit(request, response)

        provider = str(getattr(self.adapter, "provider", "unknown"))
        model = str(getattr(self.adapter, "model", "unknown"))
        degraded_warning = ""
        try:
            draft = self.adapter.answer(request, manifest)
        except Exception as exc:
            degraded_warning = f"Provider unavailable ({type(exc).__name__}); deterministic guide used."
            draft = self.fallback_adapter.answer(request, manifest)
            provider = "deterministic-fallback"
            model = str(getattr(self.fallback_adapter, "model", "section-guide-v1"))

        response_decision = self.policy.evaluate_draft(draft, manifest)
        if not response_decision.allowed:
            response = self._blocked_response(request, response_decision, started)
            return self._remember_and_audit(request, response)

        warnings = draft.warnings
        if degraded_warning:
            warnings = (*warnings, degraded_warning)
        response = SectionAgentResponse(
            run_id=uuid4().hex,
            request_id=request_id,
            section_id=manifest.section_id,
            status=draft.status,
            answer_markdown=draft.answer_markdown,
            evidence_grade=draft.evidence_grade,
            policy_decision=response_decision,
            context_hash=request.context.context_hash,
            citations=draft.citations,
            facts=draft.facts,
            assumptions=draft.assumptions,
            unknowns=draft.unknowns,
            suggested_actions=draft.suggested_actions,
            warnings=warnings,
            provider=provider,
            model=model,
            latency_ms=max(0, int((time.perf_counter() - started) * 1_000)),
        )
        return self._remember_and_audit(request, response)

    def _blocked_response(
        self,
        request: SectionAgentRequest,
        decision: PolicyDecision,
        started: float,
    ) -> SectionAgentResponse:
        return SectionAgentResponse(
            run_id=uuid4().hex,
            request_id=request.effective_request_id or uuid4().hex,
            section_id=request.section_id,
            status=ResponseStatus.POLICY_BLOCKED,
            answer_markdown=(
                "Cette demande dépasse la frontière **RESEARCH_ONLY** de l’assistant. "
                f"{decision.reason} Je peux toutefois expliquer les données, préparer une analyse ou guider la navigation."
            ),
            evidence_grade=EvidenceGrade.UNKNOWN,
            policy_decision=decision,
            context_hash=request.context.context_hash,
            provider="policy",
            model="deterministic-policy-v1",
            latency_ms=max(0, int((time.perf_counter() - started) * 1_000)),
        )

    def _remember_and_audit(
        self,
        request: SectionAgentRequest,
        response: SectionAgentResponse,
    ) -> SectionAgentResponse:
        self._responses[response.request_id] = response
        if len(self._responses) > 128:
            first_key = next(iter(self._responses))
            self._responses.pop(first_key, None)
        try:
            message_hash = hashlib.sha256(request.message.encode("utf-8")).hexdigest()
            self.audit_store.append(
                SectionAuditRecord(
                    run_id=response.run_id,
                    request_id=response.request_id,
                    section_id=response.section_id,
                    conversation_id=request.context.conversation_id,
                    user_id=request.context.user_id,
                    tenant_id=request.context.tenant_id,
                    message_hash=message_hash,
                    context_hash=response.context_hash,
                    status=response.status,
                    evidence_grade=response.evidence_grade,
                    policy_decision=response.policy_decision,
                    provider=response.provider,
                    model=response.model,
                    latency_ms=response.latency_ms,
                )
            )
        except OSError:
            pass
        return response

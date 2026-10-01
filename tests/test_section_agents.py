from __future__ import annotations

import json

from quant_ai.config import ProviderSettings
from quant_ai.section_agents import (
    EvidenceGrade,
    LLMSectionAdapter,
    ResponseStatus,
    SectionAgentRequest,
    SectionAgentService,
    SectionAuditStore,
    SectionContextBuilder,
    build_default_section_registry,
)


def _request(section: str, message: str, raw: dict | None = None) -> SectionAgentRequest:
    registry = build_default_section_registry()
    context = SectionContextBuilder(registry).build(section, raw or {})
    return SectionAgentRequest(section_id=section, message=message, context=context)


def test_context_is_allowlisted_bounded_and_secret_free() -> None:
    context = _request(
        "risk",
        "Explain this screen",
        {
            "security": "SPY",
            "primary_function": "Risk Monitor",
            "api_key": "must-never-survive",
            "unrelated_session_state": "drop-me",
            "data_as_of": "2026-10-01T20:00:00Z",
            "section_state": {
                "analysis_available": True,
                "risk_metrics": {"var": 1.25, "password": "drop-me"},
                "portfolio_holdings": ["drop-me"],
            },
        },
    ).context

    encoded = json.dumps(context.to_dict())
    assert context.security == "SPY"
    assert context.primary_function == "Risk Monitor"
    assert context.section_state == {
        "analysis_available": True,
        "risk_metrics": {"var": 1.25},
    }
    assert "must-never-survive" not in encoded
    assert "drop-me" not in encoded
    assert len(context.context_hash) == 64


def test_deterministic_guide_answers_navigation_without_provider(tmp_path) -> None:
    service = SectionAgentService(
        audit_store=SectionAuditStore(tmp_path / "audit.jsonl"),
    )
    response = service.answer(
        _request(
            "backtest",
            "Aide-moi à utiliser cette section",
            {"security": "SPY", "data_as_of": "2026-10-01"},
        )
    )

    assert response.status == ResponseStatus.ANSWERED
    assert "Backtest Lab" in response.answer_markdown
    assert response.provider == "deterministic"
    assert response.policy_decision.allowed
    records = SectionAuditStore(tmp_path / "audit.jsonl").recent()
    assert records[0]["section_id"] == "backtest"
    assert "answer_markdown" not in records[0]


def test_arbitrary_question_is_explicitly_not_connected() -> None:
    response = SectionAgentService().answer(
        _request("company", "Quelle est la juste valeur actuelle ?", {"security": "NVDA"})
    )

    assert response.status == ResponseStatus.NOT_CONNECTED
    assert "aucun modèle conversationnel" in response.answer_markdown
    assert response.evidence_grade == EvidenceGrade.UNKNOWN


def test_financial_execution_request_is_blocked_before_adapter() -> None:
    class ExplodingAdapter:
        provider = "should-not-run"
        model = "should-not-run"

        def answer(self, request, manifest):  # pragma: no cover - must never run
            raise AssertionError("adapter was called")

    response = SectionAgentService(adapter=ExplodingAdapter()).answer(
        _request("options", "Passe un ordre maintenant pour acheter ce trade")
    )

    assert response.status == ResponseStatus.POLICY_BLOCKED
    assert response.policy_decision.code == "FINANCIAL_ACTION_DENIED"
    assert response.provider == "policy"


def test_provider_failure_falls_back_without_losing_the_question() -> None:
    class FailingAdapter:
        provider = "test-provider"
        model = "test-model"

        def answer(self, request, manifest):
            raise TimeoutError("provider timeout")

    response = SectionAgentService(adapter=FailingAdapter()).answer(
        _request("risk", "Aide-moi à utiliser cette section", {"security": "SPY"})
    )

    assert response.status == ResponseStatus.ANSWERED
    assert response.provider == "deterministic-fallback"
    assert any("Provider unavailable" in warning for warning in response.warnings)


def test_llm_adapter_rejects_fabricated_citations() -> None:
    adapter = LLMSectionAdapter(ProviderSettings(), "test-key")
    adapter.client.complete_json = lambda *_args, **_kwargs: {
        "answer_markdown": "Méthode générale, sans donnée live.",
        "status": "ANSWERED",
        "evidence_grade": "VERIFIED",
        "facts": [],
        "assumptions": ["Exemple pédagogique"],
        "unknowns": ["Données live absentes"],
        "warnings": [],
        "citations": [{"source_id": "invented-source"}],
    }
    service = SectionAgentService(adapter=adapter)
    response = service.answer(_request("rates", "Explique la courbe"))

    assert response.status == ResponseStatus.ANSWERED
    assert response.citations == ()
    assert response.evidence_grade == EvidenceGrade.INFERRED


def test_request_id_is_idempotent_within_service() -> None:
    registry = build_default_section_registry()
    context = SectionContextBuilder(registry).build("risk", {}, request_id="same-turn")
    request = SectionAgentRequest("risk", "Aide-moi", context)
    service = SectionAgentService(registry=registry)

    first = service.answer(request)
    second = service.answer(request)
    assert second is first

"""Streamlit shell for a namespaced contextual section assistant."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import html
from typing import Any
from uuid import uuid4

import streamlit as st

from quant_ai.config import ProviderSettings
from quant_ai.section_agents import (
    DeterministicSectionAdapter,
    LLMSectionAdapter,
    SectionAgentRegistry,
    SectionAgentRequest,
    SectionAgentService,
    SectionContextBuilder,
    build_default_section_registry,
)
from quant_ai.section_agents.registry import resolve_section_id as _resolve_section_id


PROVIDERS = (
    "OpenAI",
    "Anthropic",
    "Google Gemini",
    "OpenRouter",
    "Mistral",
    "Groq",
    "Custom OpenAI-compatible",
    "Deterministic",
)
DEFAULT_MODELS = {
    "OpenAI": "gpt-5.2",
    "Anthropic": "claude-sonnet-4-5",
    "Google Gemini": "gemini-2.5-pro",
    "OpenRouter": "openai/gpt-5.2",
    "Mistral": "mistral-large-latest",
    "Groq": "llama-3.3-70b-versatile",
    "Custom OpenAI-compatible": "your-model",
    "Deterministic": "deterministic",
}

STATUS_LABELS = {
    "ANSWERED": "RÉPONSE",
    "NEEDS_CLARIFICATION": "PRÉCISION REQUISE",
    "WAITING_EVIDENCE": "PREUVE REQUISE",
    "NOT_CONNECTED": "GUIDE LOCAL",
    "POLICY_BLOCKED": "ACTION BLOQUÉE",
    "DEGRADED_ERROR": "MODE DÉGRADÉ",
}


def resolve_section_id(mode_or_route: str) -> str | None:
    return _resolve_section_id(mode_or_route)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .sa-context {display:flex;flex-wrap:wrap;gap:.38rem;margin:.2rem 0 .7rem}
        .sa-chip {border:1px solid rgba(80,190,220,.24);background:rgba(9,25,39,.72);
          border-radius:999px;padding:.23rem .56rem;color:#bcd1de;font-size:.72rem;font-weight:700;letter-spacing:.025em}
        .sa-chip.live {border-color:rgba(70,220,171,.34);color:#78edc4}
        .sa-status {font-size:.69rem;letter-spacing:.09em;font-weight:850;color:#70dfc1;margin-bottom:.25rem}
        .sa-meta {font-size:.71rem;color:#7f93a3;margin-top:.45rem}
        .sa-note {border-left:2px solid rgba(95,180,225,.35);padding:.25rem .65rem;color:#91a6b4;font-size:.78rem}
        .sa-source {font-size:.76rem;color:#9fb3c0;padding:.14rem 0}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _safe(value: Any) -> str:
    return html.escape(str(value or ""))


def _set_question(key: str, value: str) -> None:
    st.session_state[key] = value


def _disconnect_key(local_key: str) -> None:
    st.session_state["qai_api_key"] = ""
    st.session_state[local_key] = ""


def _provider_configuration(section_id: str) -> tuple[ProviderSettings, str, bool]:
    current_provider = str(st.session_state.get("qai_provider") or "OpenAI")
    if current_provider not in PROVIDERS:
        current_provider = "OpenAI"
    provider_key = f"section_agent_provider::{section_id}"
    model_key = f"section_agent_model::{section_id}"
    local_api_key = f"section_agent_api_key::{section_id}"
    base_url_key = f"section_agent_base_url::{section_id}"

    st.session_state.setdefault(provider_key, current_provider)
    st.session_state.setdefault(
        model_key,
        str(st.session_state.get("qai_model") or DEFAULT_MODELS[current_provider]),
    )
    st.session_state.setdefault(local_api_key, str(st.session_state.get("qai_api_key") or ""))
    st.session_state.setdefault(base_url_key, str(st.session_state.get("qai_base_url") or ""))

    with st.popover("Modèle IA", help="Connexion BYOK limitée à cette session Streamlit"):
        provider = st.selectbox("Fournisseur", PROVIDERS, key=provider_key)
        default_model = DEFAULT_MODELS[provider]
        if str(st.session_state.get(model_key) or "") in DEFAULT_MODELS.values() and provider != current_provider:
            st.session_state[model_key] = default_model
        model = st.text_input("Modèle", key=model_key)
        base_url = st.text_input(
            "Base URL (optionnelle)",
            key=base_url_key,
            help="Requise pour un fournisseur OpenAI-compatible personnalisé.",
        )
        if provider != "Deterministic":
            api_key = st.text_input(
                "Clé API de session",
                type="password",
                key=local_api_key,
                autocomplete="off",
                help="Conservée dans cette session uniquement; jamais envoyée aux logs d'audit.",
            )
        else:
            api_key = ""
            st.caption("Mode local : aucune requête n’est envoyée à un fournisseur.")
        st.button(
            "Déconnecter la clé",
            key=f"section_agent_disconnect::{section_id}",
            on_click=_disconnect_key,
            args=(local_api_key,),
            disabled=not bool(str(st.session_state.get(local_api_key) or "")),
        )

    st.session_state["qai_provider"] = provider
    st.session_state["qai_model"] = str(model or default_model).strip()
    st.session_state["qai_base_url"] = str(base_url or "").strip()
    st.session_state["qai_api_key"] = str(api_key or "").strip()
    connected = provider != "Deterministic" and bool(st.session_state["qai_api_key"])
    settings = ProviderSettings(
        provider=provider,
        model=st.session_state["qai_model"],
        base_url=st.session_state["qai_base_url"],
        temperature=float(st.session_state.get("qai_temperature") or 0.15),
        timeout_seconds=int(st.session_state.get("qai_timeout") or 90),
        max_output_tokens=min(4_000, int(st.session_state.get("qai_max_tokens") or 2_200)),
    )
    return settings, st.session_state["qai_api_key"], connected


def _build_service(
    registry: SectionAgentRegistry,
    settings: ProviderSettings,
    api_key: str,
    connected: bool,
) -> SectionAgentService:
    adapter = LLMSectionAdapter(settings, api_key) if connected else DeterministicSectionAdapter()
    return SectionAgentService(registry=registry, adapter=adapter)


def _render_response(entry: Mapping[str, Any]) -> None:
    status = str(entry.get("status") or "UNKNOWN")
    st.markdown(
        f'<div class="sa-status">{_safe(STATUS_LABELS.get(status, status))} · '
        f'{_safe(entry.get("evidence_grade") or "UNKNOWN")}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(str(entry.get("answer_markdown") or ""))

    assumptions = entry.get("assumptions") or []
    unknowns = entry.get("unknowns") or []
    warnings = entry.get("warnings") or []
    citations = entry.get("citations") or []
    if assumptions or unknowns or warnings or citations:
        with st.container(border=True):
            if citations:
                st.caption("PREUVES RÉSOLUBLES")
                for citation in citations:
                    if not isinstance(citation, Mapping):
                        continue
                    st.markdown(
                        f'<div class="sa-source">{_safe(citation.get("title") or citation.get("source_id"))}'
                        f' · as of {_safe(citation.get("as_of") or "non indiqué")}</div>',
                        unsafe_allow_html=True,
                    )
            if assumptions:
                st.caption("Hypothèses · " + " · ".join(str(item) for item in assumptions[:6]))
            if unknowns:
                st.caption("Inconnues · " + " · ".join(str(item) for item in unknowns[:6]))
            for warning in warnings[:4]:
                st.warning(str(warning), icon="⚠️")

    st.markdown(
        f'<div class="sa-meta">{_safe(entry.get("provider"))} · {_safe(entry.get("model"))} · '
        f'{_safe(entry.get("latency_ms"))} ms · trace {_safe(str(entry.get("run_id") or "")[:10])}</div>',
        unsafe_allow_html=True,
    )


def render_section_assistant(
    section_id: str,
    *,
    section_label: str | None = None,
    security: str | None = None,
    primary_function: str | None = None,
    raw_context: Mapping[str, Any] | None = None,
    suggestions: Sequence[str] | None = None,
    service: SectionAgentService | None = None,
    registry: SectionAgentRegistry | None = None,
    expanded: bool = False,
    locale: str = "fr-FR",
) -> None:
    """Render one contextual assistant without exposing the full session state."""

    registry = registry or build_default_section_registry()
    manifest = registry.require(section_id)
    section_id = manifest.section_id
    label = section_label or manifest.label
    _inject_css()

    history_key = f"section_agent_history::{section_id}"
    question_key = f"section_agent_question::{section_id}"
    conversation_key = f"section_agent_conversation::{section_id}"
    st.session_state.setdefault(history_key, [])
    st.session_state.setdefault(conversation_key, uuid4().hex)
    st.session_state.setdefault(question_key, "")

    with st.expander(
        f"◈ ASSISTANT {label.upper()} · SUPPORT CONTEXTUEL",
        expanded=expanded,
    ):
        settings, api_key, connected = _provider_configuration(section_id)
        mode_text = f"MODÈLE CONNECTÉ · {settings.provider}" if connected else "GUIDE LOCAL · IA NON CONNECTÉE"
        state_context = dict(raw_context or {})
        state_context.setdefault("security", security or "")
        state_context.setdefault("primary_function", primary_function or label)
        data_as_of = str(state_context.get("data_as_of") or "non disponible")
        st.markdown(
            '<div class="sa-context">'
            f'<span class="sa-chip live">{_safe(mode_text)}</span>'
            f'<span class="sa-chip">SECTION · {_safe(label)}</span>'
            f'<span class="sa-chip">SECURITY · {_safe(security or manifest.default_symbol)}</span>'
            f'<span class="sa-chip">FUNCTION · {_safe(primary_function or manifest.label)}</span>'
            f'<span class="sa-chip">AS OF · {_safe(data_as_of)}</span>'
            '<span class="sa-chip">RESEARCH ONLY</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="sa-note">Posez une question sur la section, ses contrôles, ses méthodes ou ses résultats. '
            'Les données absentes restent explicitement inconnues; aucune action financière ne peut être exécutée.</div>',
            unsafe_allow_html=True,
        )

        history = st.session_state.get(history_key)
        if not isinstance(history, list):
            history = []
            st.session_state[history_key] = history
        for turn in history[-10:]:
            if not isinstance(turn, Mapping):
                continue
            with st.chat_message("user"):
                st.markdown(str(turn.get("question") or ""))
            with st.chat_message("assistant"):
                response = turn.get("response")
                if isinstance(response, Mapping):
                    _render_response(response)

        prompt_suggestions = tuple(suggestions or manifest.quick_actions)[:5]
        if prompt_suggestions:
            st.caption("QUESTIONS GUIDÉES")
            columns = st.columns(min(3, len(prompt_suggestions)))
            for index, suggestion in enumerate(prompt_suggestions):
                columns[index % len(columns)].button(
                    str(suggestion),
                    key=f"section_agent_suggestion::{section_id}::{index}",
                    width="stretch",
                    on_click=_set_question,
                    args=(question_key, str(suggestion)),
                )

        with st.form(f"section_agent_form::{section_id}", clear_on_submit=False):
            st.text_area(
                "Votre question",
                key=question_key,
                height=88,
                placeholder=f"Ex. Explique-moi comment utiliser {label} avec le contexte actuel…",
            )
            submitted = st.form_submit_button(
                "ANALYSER AVEC L’ASSISTANT",
                type="primary",
                width="stretch",
            )

        if submitted:
            question = str(st.session_state.get(question_key) or "").strip()
            context_builder = SectionContextBuilder(registry)
            context = context_builder.build(
                section_id,
                state_context,
                conversation_id=str(st.session_state[conversation_key]),
            )
            request = SectionAgentRequest(
                section_id=section_id,
                message=question,
                context=context,
                locale=locale,
            )
            active_service = service or _build_service(registry, settings, api_key, connected)
            with st.spinner("Analyse contextuelle en cours…"):
                response = active_service.answer(request)
            history.append({"question": question, "response": response.to_dict()})
            st.session_state[history_key] = history[-20:]
            st.rerun()

# Quant Terminal contextual section assistants

## Purpose

The section-assistant shell gives every routed Quant Terminal workspace a
local, context-aware guide.  It helps a user understand the active section,
interpret its available evidence, locate the next control and formulate a
research action without replacing the section's calculations or institutional
approval gates.

The release covers the 19 entries in `institutional_router.WORKSPACES`, the
Institutional Navigator, and the historical Trading Plan route.

## Runtime behaviour

- Each workspace owns a versioned `SectionManifest` with its mandate,
  allowlisted context, knowledge collections, tools, quick questions and
  prohibited capabilities.
- `SectionContextBuilder` copies only bounded, allowlisted values.  The full
  Streamlit session, provider secrets, raw dataframes and raw portfolio state
  are never forwarded.
- `SectionAgentService` applies the policy gate before answering and writes a
  redacted audit record.  The permanent governance mode is `RESEARCH_ONLY`.
- When a session provider is connected through Quant AI settings, the section
  assistant can reuse that BYOK provider and model.  The key remains only in
  `st.session_state` and is never shown or written to audit data.
- Without a connected provider, the deterministic guide remains available for
  navigation, section explanations, evidence requirements and suggested next
  questions.  The UI labels this mode explicitly.
- Every mount is fail-soft.  An import, provider or rendering failure leaves
  the underlying workspace operational.

## Coverage

Standard routes are resolved from the active terminal mode.  Autonomous routes
are mounted before their existing `st.stop()` boundary.

| Surface | Section identifiers |
| --- | --- |
| Navigator | `navigator` |
| Standard terminal | `corr`, `portfolio`, `risk`, `backtest`, `momentum`, `monte_carlo`, `company`, `options`, `decision`, `ml`, `fx`, `commodities`, `rates`, `credit`, `macro` |
| Autonomous | `market_intelligence`, `psychology`, `quant_ai`, `worldmonitor` |
| Compatibility | `trading_plan` |

The registry contract test compares the 19 workspace manifests with the
authoritative router and verifies that every route round-trips correctly.

## Safety boundary

The assistant may read bounded research context and offer reversible navigation
or preparation suggestions.  It cannot:

- submit an order or write broker state;
- allocate capital or rebalance an account;
- change a risk limit or suppress a breach;
- promote a research model to production;
- access or reveal credentials;
- execute free-form shell, SQL or Python supplied by a model.

Missing or stale evidence is surfaced as an explicit response state rather
than replaced with an invented value.  Suggested actions are advisory UI
objects; text produced by a provider is never an execution instruction.

## User workflow

1. Open the assistant expander inside a section.
2. Confirm the context chips for section, security, primary function and data
   freshness.
3. Select a suggested question or enter a section-specific question.
4. Review the answer, evidence grade, unknowns, warnings and next actions.
5. For model-backed answers, connect a BYOK provider from Quant AI settings.
   Disconnecting the key immediately returns every assistant to local fallback.

Conversation state is namespaced by section so changing workspace does not mix
two research threads.

## Developer API

```python
from quant_ai.ui_components.section_assistant import render_section_assistant

render_section_assistant(
    "risk",
    security="SPY",
    primary_function="Risk Monitor",
    raw_context={
        "data_as_of": "2026-10-01T20:00:00Z",
        "section_state": {"analysis_available": True},
        "permissions": ("read", "navigate", "prepare_research"),
    },
    locale="fr-FR",
)
```

New domain data should be exposed through a small read-only context adapter.
Do not pass a package's internal object graph or the full session state to this
function.

## Validation and operations

Targeted validation:

```bash
python -m pytest -q \
  tests/test_section_agents.py \
  tests/test_section_agent_ui.py \
  tests/test_section_agent_route_contract.py
python -m py_compile app.py quant_ai/section_agents/*.py \
  quant_ai/ui_components/section_assistant.py
```

Runtime acceptance additionally requires:

```bash
curl -fsS http://127.0.0.1:8501/_stcore/health
```

The health endpoint proves that Streamlit is serving.  It does not, by itself,
prove provider connectivity or the quality of a financial answer; those are
verified separately through the UI and the provider-labelled response state.

# Quant AI Investment OS · v4

Quant AI is an auditable research and decision layer—not a chat wrapper and not an order router. Its contracts are deliberately separable so that a client can replace a model, a desk, a prompt or an evidence adapter without rewriting the terminal.

## Runtime flow

1. `llm.py` classifies security research, strategy, portfolio, rebalance, hedge, scenario, risk, screening or general requests.
2. `tools.py` maps all relevant terminal sections into typed evidence blocks. Missing sections report `not_available`; they never become implicit assumptions.
3. `orchestrator.py` dispatches independent desk work in parallel, freezes first-pass reports, runs a peer consultation/challenge round, applies the Chief Risk gate and asks the CIO to reconcile—not average—the evidence.
4. `interactive_graph.py` turns those real dispatches, evidence calls, reports, challenges, support links and vetoes into a native Components v2 decision graph. Nodes are selectable and draggable, edges are inspectable, the canvas pans/zooms/filters, layouts persist per browser, and graph actions open the matching desk or CIO editor.
5. `quality.py` scores evidence coverage, desk independence, report contracts, adversarial review, risk governance and the final decision contract. Low-quality committees are surfaced with blockers and corrective actions rather than hidden behind a single confidence number.
6. `exports.py` creates secret-free investment memos and machine-readable decision packets, while `state.py` persists the complete decision trace. Every run records plan, evidence status, reports, interactions, dissent, model and outcome.

## Institutional desks and customization

`config.py` ships eight independent desks: Macro, Quant, Risk, Derivatives, Portfolio, Fundamental Research, Systematic Strategy and Execution. Every desk exposes editable mandate, decision rights, evidence policy, required outputs, review questions, guardrails, tools, peer consultations, model override, priority and turn limit. The CIO prompt, fund governance and consultation runtime are also client-configurable.

The BYOK layer supports OpenAI, Anthropic, Gemini, OpenRouter, Mistral, Groq and custom OpenAI-compatible endpoints. Keys are held only in the Streamlit session and are excluded from organization files and audit logs. The entire organization—including desk prompts, tools, peer routes, priorities and risk governance—can be exported or imported as a portable JSON configuration.

## Research labs

- `strategy.py` provides explicit rules, one-bar shifted signals, fees and slippage, chronological in/out-of-sample evaluation, walk-forward folds, neighboring-parameter stability, out-of-sample bootstrap distributions, doubled-cost stress, declared-trial warnings and validation gates. It promotes a research candidate only; it never approves capital.
- `portfolio.py` reviews gross/net/cash, concentration, effective bets, approximate risk contribution, mandate breaches, liquidity, four scenario shocks, a 10,000-path annual return distribution and a proposal-only concentration/cash rebalance. Its constant-correlation result is visibly labeled approximate until a full covariance source is connected.

## Decision-room interaction contract

The workflow is application state, not a decorative image. A node click returns the selected desk/tool to Python, and an action returns a nonce-backed event that Streamlit applies once. Editing an agent updates the same `OrganizationConfig` consumed by the orchestrator on the next run. Dynamic prompts and reports are written into the component with DOM `textContent`; they are never evaluated as HTML. The legacy SVG remains only as a graceful fallback and as a non-interactive progress view while a committee is running.

The Human IC node deliberately remains outside model autonomy. The system may research, challenge, simulate and recommend; it cannot silently turn a proposal into an order.

Every trade, rebalance, hedge or allocation remains a proposal requiring explicit human approval. The deterministic path keeps the committee operational and testable when a provider is absent or unavailable.

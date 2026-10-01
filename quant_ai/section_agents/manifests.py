"""Static, dependency-light manifests for the Institutional Navigator."""

from __future__ import annotations

from .contracts import SectionManifest


DENIED_FINANCIAL_CAPABILITIES: tuple[str, ...] = (
    "submit_order",
    "allocate_capital",
    "modify_risk_limit",
    "promote_model",
    "write_broker_state",
    "access_credentials",
)


def _manifest(
    section_id: str,
    function: str,
    label: str,
    description: str,
    mode: str | None,
    default_asset: str,
    default_symbol: str,
    audiences: tuple[str, ...],
    *,
    special_route: str | None = None,
    force_context: bool = False,
    mandate: str,
    knowledge: tuple[str, ...],
    context: tuple[str, ...],
    tools: tuple[str, ...],
    actions: tuple[str, ...],
) -> SectionManifest:
    return SectionManifest(
        section_id=section_id,
        function=function,
        label=label,
        description=description,
        mode=mode,
        default_asset=default_asset,
        default_symbol=default_symbol,
        audiences=audiences,
        special_route=special_route,
        force_context=force_context,
        mandate=mandate,
        knowledge_collections=knowledge,
        allowed_context_keys=context,
        allowed_tools=tools,
        denied_capabilities=DENIED_FINANCIAL_CAPABILITIES,
        quick_actions=actions,
    )


WORKSPACE_MANIFEST_SEQUENCE: tuple[SectionManifest, ...] = (
    _manifest(
        "corr", "CORR", "Cross-Asset Correlation",
        "Dependencies, regimes and diversification breaks.",
        "Correlation Matrix", "Equity", "SPY", ("multi_asset", "macro", "risk", "cio"),
        mandate="Explain dependency, regime and diversification diagnostics without treating correlation as stable or causal.",
        knowledge=("correlation_methodology", "dependency_metrics", "diversification_governance"),
        context=("correlation_matrix", "correlation_regime", "dependency_results", "cluster_results"),
        tools=("correlation_context", "market_snapshot", "risk_snapshot", "section_inventory"),
        actions=("Explain the current correlation regime", "Identify diversification breaks", "Check data coverage"),
    ),
    _manifest(
        "portfolio", "PORT", "Portfolio Lab",
        "Allocation, optimization, attribution and portfolio construction.",
        "Portfolio Lab", "Equity", "SPY", ("multi_asset", "risk", "cio", "wealth"),
        mandate="Guide portfolio research, attribution and mandate diagnostics without allocating capital or rebalancing accounts.",
        knowledge=("portfolio_methodology", "allocation_metrics", "portfolio_governance"),
        context=("portfolio", "holdings", "allocation", "portfolio_metrics", "attribution", "mandate"),
        tools=("portfolio_context", "portfolio_diagnostics", "risk_snapshot", "market_snapshot", "section_inventory"),
        actions=("Explain portfolio exposures", "Review mandate diagnostics", "Show the evidence needed before a rebalance"),
    ),
    _manifest(
        "risk", "RISK", "Risk Monitor",
        "Volatility, drawdown, exposure and stress surveillance.",
        "Risk Monitor", "Equity", "SPY", ("multi_asset", "risk", "cio", "wealth"),
        mandate="Explain risk measurements and stress evidence while preserving independent risk authority and limits.",
        knowledge=("risk_methodology", "stress_testing", "risk_governance"),
        context=("risk_metrics", "exposures", "stress_results", "risk_limits", "breaches"),
        tools=("risk_snapshot", "portfolio_diagnostics", "market_snapshot", "section_inventory"),
        actions=("Explain current risk metrics", "Review stress scenarios", "Check evidence freshness"),
    ),
    _manifest(
        "backtest", "BT", "Backtest Lab",
        "Research hypotheses with controlled historical validation.",
        "Backtest Lab", "Equity", "SPY", ("multi_asset", "equity", "macro", "risk"),
        mandate="Guide no-look-ahead, cost-aware historical research and clearly separate diagnostics from investable evidence.",
        knowledge=("backtest_methodology", "statistical_validation", "execution_assumptions"),
        context=("backtest", "strategy", "performance", "validation", "walk_forward", "cost_model"),
        tools=("backtest_context", "strategy_backtest", "market_snapshot", "risk_snapshot", "technical_regime", "section_inventory"),
        actions=("Explain this backtest", "Inspect look-ahead and cost assumptions", "Review out-of-sample evidence"),
    ),
    _manifest(
        "momentum", "MOM", "Momentum / Trend",
        "Trend state, breadth and momentum diagnostics.",
        "Momentum / Trend", "Equity", "SPY", ("multi_asset", "equity", "macro"),
        mandate="Explain trend, breadth, regime and invalidation evidence without turning a diagnostic into an order signal.",
        knowledge=("momentum_methodology", "trend_regimes", "signal_governance"),
        context=("momentum", "trend", "regime", "signals", "breadth", "invalidation"),
        tools=("technical_regime", "market_snapshot", "risk_snapshot", "section_inventory"),
        actions=("Explain the current regime", "Interpret momentum signals", "Show invalidation conditions"),
    ),
    _manifest(
        "monte_carlo", "MC", "Monte Carlo Advanced",
        "Path simulation, scenario distributions and tail outcomes.",
        "Monte Carlo Advanced", "Equity", "SPY", ("multi_asset", "risk", "equity"),
        mandate="Explain simulations, assumptions and tail distributions without presenting simulated paths as forecasts.",
        knowledge=("monte_carlo_methodology", "scenario_design", "simulation_limitations"),
        context=("monte_carlo", "simulation", "scenario", "distribution", "percentiles", "assumptions"),
        tools=("monte_carlo_context", "market_snapshot", "risk_snapshot", "section_inventory"),
        actions=("Explain the simulated distribution", "Review model assumptions", "Inspect tail scenarios"),
    ),
    _manifest(
        "company", "COMP", "Company Intelligence",
        "Fundamentals, valuation, management and catalysts.",
        "Company Intelligence", "Equity", "NVDA", ("equity", "cio", "wealth"),
        force_context=True,
        mandate="Guide company research with dated, traceable fundamental evidence and explicit uncertainty.",
        knowledge=("company_research", "fundamental_metrics", "valuation_methodology"),
        context=("company", "fundamentals", "valuation", "earnings", "management", "catalysts", "peers"),
        tools=("company_intelligence", "market_snapshot", "technical_regime", "risk_snapshot", "section_inventory"),
        actions=("Explain the company snapshot", "Review valuation assumptions", "Identify catalysts and risks"),
    ),
    _manifest(
        "options", "OMON", "Options / Futures",
        "Derivatives surfaces, structures and execution context.",
        "Options / Futures", "Equity", "SPY", ("equity", "macro", "risk"),
        mandate="Explain derivatives structures, surfaces and risk without recommending or executing a trade.",
        knowledge=("derivatives_methodology", "options_greeks", "futures_execution"),
        context=("options", "futures", "surface", "greeks", "term_structure", "strategies", "execution"),
        tools=("derivatives_context", "execution_context", "risk_snapshot", "market_snapshot", "section_inventory"),
        actions=("Explain the volatility surface", "Review Greeks and scenarios", "Check execution assumptions"),
    ),
    _manifest(
        "decision", "DCSN", "Decision Engine",
        "Evidence synthesis and auditable decision framing.",
        "Decision Engine", "Equity", "SPY", ("multi_asset", "equity", "cio", "wealth"),
        mandate="Frame evidence, dissent and invalidation while leaving all institutional and human gates controlling.",
        knowledge=("decision_framework", "evidence_governance", "human_approval"),
        context=("decision", "evidence", "dissent", "gates", "invalidation", "recommendation_state"),
        tools=("section_inventory", "market_snapshot", "risk_snapshot", "portfolio_diagnostics"),
        actions=("Explain the evidence chain", "Show unresolved dissent", "Review controlling gates"),
    ),
    _manifest(
        "ml", "BQLAB", "ML Research Lab",
        "Feature research and model diagnostics.",
        "ML Research Lab", "Equity", "SPY", ("multi_asset", "equity"),
        mandate="Explain model, feature, OOS and drift diagnostics without promoting a model or authorizing capital.",
        knowledge=("ml_methodology", "model_validation", "drift_governance"),
        context=("ml", "features", "model_results", "cross_validation", "calibration", "drift", "champion_challenger"),
        tools=("ml_research_context", "market_snapshot", "risk_snapshot", "section_inventory"),
        actions=("Explain model diagnostics", "Review out-of-sample design", "Inspect drift and calibration"),
    ),
    _manifest(
        "fx", "FXGO", "FX Dashboard",
        "Majors, crosses, dollar regime and relative momentum.",
        "FX Dashboard", "FX", "EURUSD=X", ("macro", "multi_asset"),
        force_context=True,
        mandate="Explain FX regimes, relative drivers and risk with explicit pair, tenor and data context.",
        knowledge=("fx_methodology", "macro_transmission", "currency_risk"),
        context=("fx", "currency_pair", "dollar_regime", "relative_momentum", "carry", "macro_drivers"),
        tools=("macro_context", "market_snapshot", "technical_regime", "risk_snapshot", "section_inventory"),
        actions=("Explain the FX regime", "Review relative drivers", "Check pair and horizon context"),
    ),
    _manifest(
        "commodities", "CMDTY", "Commodity Dashboard",
        "Energy, metals, agriculture and inflation transmission.",
        "Commodity Dashboard", "Commodities", "GC=F", ("macro", "multi_asset"),
        force_context=True,
        mandate="Explain commodity regimes, curves and transmission channels without converting research into a position.",
        knowledge=("commodity_methodology", "curve_structure", "inflation_transmission"),
        context=("commodities", "curve", "inventory", "seasonality", "inflation", "supply_demand"),
        tools=("macro_context", "market_snapshot", "technical_regime", "risk_snapshot", "section_inventory"),
        actions=("Explain the commodity regime", "Review curve and inventory context", "Trace inflation transmission"),
    ),
    _manifest(
        "rates", "GOVT", "Rates Dashboard",
        "Sovereign curves, duration and policy repricing.",
        "Rates Dashboard", "Rates", "^TNX", ("macro", "risk", "multi_asset"),
        force_context=True,
        mandate="Explain sovereign curves, duration and policy repricing with explicit tenor and as-of context.",
        knowledge=("rates_methodology", "yield_curve", "central_bank_policy"),
        context=("rates", "yield_curve", "duration", "policy_path", "term_premium", "sovereign"),
        tools=("fixed_income_context", "macro_context", "market_snapshot", "risk_snapshot", "section_inventory"),
        actions=("Explain the yield curve", "Review duration risk", "Trace policy repricing"),
    ),
    _manifest(
        "credit", "CRPR", "Fixed Income & Credit",
        "Curve, spread, DV01, CS01 and relative-value analytics.",
        "Fixed Income & Credit Analytics", "Rates", "LQD", ("macro", "risk", "cio", "wealth"),
        force_context=True,
        mandate="Explain fixed-income and credit analytics while preserving liquidity, spread and data-quality caveats.",
        knowledge=("fixed_income_methodology", "credit_spreads", "duration_risk"),
        context=("fixed_income", "credit", "curve", "spreads", "dv01", "cs01", "relative_value", "liquidity"),
        tools=("fixed_income_context", "macro_context", "risk_snapshot", "market_snapshot", "section_inventory"),
        actions=("Explain spread and curve metrics", "Review DV01 and CS01", "Check liquidity evidence"),
    ),
    _manifest(
        "macro", "ECON", "Macro / Central Banks",
        "Growth, inflation, liquidity and policy regime.",
        "Macro / Central Banks", "Equity", "SPY", ("macro", "multi_asset", "cio"),
        force_context=True,
        mandate="Explain macro regimes and policy evidence with vintage-aware data and no look-ahead claims.",
        knowledge=("macro_methodology", "central_bank_policy", "economic_data_vintages"),
        context=("macro", "growth", "inflation", "liquidity", "policy", "economic_releases", "vintages"),
        tools=("macro_context", "market_snapshot", "risk_snapshot", "event_intelligence", "section_inventory"),
        actions=("Explain the macro regime", "Review central-bank evidence", "Check data vintages"),
    ),
    _manifest(
        "market_intelligence", "MINT", "Market Intelligence",
        "Catalysts, information absorption, microstructure and probabilistic forecasts.",
        None, "Equity", "NVDA", ("multi_asset", "equity", "macro", "risk", "cio"),
        special_route="market-intelligence",
        mandate="Explain catalysts and probabilistic market evidence without treating classification diagnostics as alpha.",
        knowledge=("market_intelligence", "catalyst_methodology", "forecast_governance"),
        context=("market_intelligence", "catalysts", "information_absorption", "microstructure", "forecasts", "patterns"),
        tools=("market_snapshot", "execution_context", "event_intelligence", "risk_snapshot", "section_inventory"),
        actions=("Explain current catalysts", "Review evidence absorption", "Inspect forecast assumptions"),
    ),
    _manifest(
        "psychology", "PSYC", "Market Psychology",
        "Narratives, positioning, reflexivity and behavioral state.",
        None, "Equity", "SPY", ("multi_asset", "equity", "cio"),
        special_route="market-psychology",
        mandate="Explain behavioral and positioning diagnostics while distinguishing observed data from narrative inference.",
        knowledge=("behavioral_finance", "positioning_metrics", "reflexivity"),
        context=("psychology", "sentiment", "positioning", "narratives", "reflexivity", "attention", "crowding"),
        tools=("behavioral_context", "market_snapshot", "risk_snapshot", "event_intelligence", "section_inventory"),
        actions=("Explain the behavioral state", "Separate facts from narratives", "Review crowding evidence"),
    ),
    _manifest(
        "quant_ai", "ASKQ", "Quant AI · CIO",
        "Cross-domain research assistant and investment committee.",
        None, "Equity", "SPY", ("multi_asset", "equity", "macro", "risk", "cio", "wealth"),
        special_route="quant-ai",
        mandate="Coordinate only the necessary specialists, preserve dissent and keep independent gates controlling.",
        knowledge=("quant_ai_governance", "committee_methodology", "evidence_lineage"),
        context=("committee", "agent_reports", "interactions", "evidence", "gates", "decision_brief"),
        tools=("section_inventory", "market_snapshot", "risk_snapshot", "portfolio_diagnostics"),
        actions=("Explain the committee workflow", "Show specialist coverage", "Review governance gates"),
    ),
    _manifest(
        "worldmonitor", "WMRD", "WorldMonitor",
        "Geopolitical events, transmission channels and scenarios.",
        None, "Equity", "SPY", ("macro", "multi_asset", "cio"),
        special_route="worldmonitor",
        mandate="Explain geopolitical events and transmission scenarios with source, time and uncertainty discipline.",
        knowledge=("worldmonitor", "geopolitical_risk", "scenario_transmission"),
        context=("worldmonitor", "events", "geopolitics", "countries", "conflicts", "supply_chains", "scenarios"),
        tools=("event_intelligence", "macro_context", "risk_snapshot", "section_inventory"),
        actions=("Explain the selected event", "Trace market transmission channels", "Review scenario uncertainty"),
    ),
)


WORKSPACE_CODES: tuple[str, ...] = tuple(
    manifest.section_id for manifest in WORKSPACE_MANIFEST_SEQUENCE
)
WORKSPACE_MANIFESTS: dict[str, SectionManifest] = {
    manifest.section_id: manifest for manifest in WORKSPACE_MANIFEST_SEQUENCE
}


NAVIGATOR_MANIFEST = _manifest(
    "navigator", "NAV", "Institutional Navigator",
    "Security and primary-function routing across Quant Terminal workspaces.",
    None, "Equity", "SPY", ("multi_asset", "equity", "macro", "risk", "cio", "wealth"),
    mandate="Guide workspace selection while preserving the user's Security and Primary Function choices.",
    knowledge=("navigator_guide", "workspace_catalogue", "routing_governance"),
    context=("recommended_workspaces", "selected_workspaces", "client_profile", "market_signal", "workspace_catalogue"),
    tools=("section_inventory",),
    actions=("Help me choose a workspace", "Explain the recommended workspaces", "Guide me through the terminal"),
)


TRADING_PLAN_MANIFEST = _manifest(
    "trading_plan", "PLAN", "Trading Plan",
    "Historical research shell for conditional implementation planning and human review.",
    "Trading Plan", "Equity", "SPY", ("multi_asset", "equity", "macro", "risk", "cio", "wealth"),
    mandate=(
        "Explain conditional research plans, evidence, invalidation and implementation constraints. "
        "Never submit an order, allocate capital or represent a plan as approved for production."
    ),
    knowledge=("trading_plan_guide", "implementation_constraints", "human_approval"),
    context=("trading_plan", "entry_conditions", "invalidation", "risk_budget", "implementation", "approval_state"),
    tools=("market_snapshot", "risk_snapshot", "portfolio_diagnostics", "execution_context", "section_inventory"),
    actions=("Explain the conditional plan", "Review invalidation criteria", "Show missing approvals"),
)


ALL_SECTION_MANIFESTS: tuple[SectionManifest, ...] = (
    *WORKSPACE_MANIFEST_SEQUENCE,
    NAVIGATOR_MANIFEST,
    TRADING_PLAN_MANIFEST,
)

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from quant_ai.config import OrganizationConfig, ProviderSettings, default_organization
from quant_ai.exports import decision_packet_json, decision_packet_markdown
from quant_ai.interactive_graph import workflow_payload
from quant_ai.llm import classify_request
from quant_ai.orchestrator import CommitteeOrchestrator
from quant_ai.portfolio import PortfolioMandate, review_portfolio
from quant_ai.quality import evaluate_committee
from quant_ai.schemas import RequestKind
from quant_ai.strategy import StrategySpec, run_strategy_backtest
from quant_ai.tools import QuantContext, build_default_registry
from quant_ai.visualization import workflow_graph_html


def price_frame(rows: int = 420) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="B")
    cycle = np.sin(np.arange(rows) / 17.0) * 1.4
    trend = 100.0 * np.exp(np.arange(rows) * 0.0006)
    return pd.DataFrame({"Close": trend + cycle}, index=index)


class QuantAIV3Tests(unittest.TestCase):
    def test_request_router_covers_strategy_portfolio_and_hedge(self) -> None:
        self.assertEqual(classify_request("Backtest cette stratégie momentum"), RequestKind.STRATEGY_TEST)
        self.assertEqual(classify_request("Rééquilibre ce portefeuille"), RequestKind.REBALANCE)
        self.assertEqual(classify_request("Conçois une couverture options"), RequestKind.HEDGE_DESIGN)

    def test_strategy_gate_has_chronological_oos_and_cost_stress(self) -> None:
        spec = StrategySpec(cost_bps=6.0, slippage_bps=4.0, trials_declared=3)
        result = run_strategy_backtest(price_frame(), spec)
        self.assertIn(result.status, {"validated_candidate", "research_only"})
        self.assertGreater(result.out_of_sample.get("observations", 0), 0)
        self.assertIn("validation_score", result.summary)
        self.assertIn("double_cost_oos_return", result.summary)
        self.assertTrue(any("shifted one bar" in item for item in result.diagnostics))
        self.assertGreaterEqual(len(result.walk_forward), 3)
        self.assertIn("positive_oos_fraction", result.robustness)
        self.assertIn("bootstrap_oos", result.robustness)
        self.assertIn("methodology_score", result.summary)
        self.assertIn("economic_score", result.summary)
        if float(result.summary.get("cagr") or 0.0) <= 0 or float(result.summary.get("sharpe") or 0.0) < 0.25:
            self.assertLessEqual(result.summary["validation_score"], 69)

    def test_portfolio_review_enforces_mandate_and_scenarios(self) -> None:
        book = {
            "holdings": [
                {"ticker": "AAA", "weight": 0.55, "expected_return": 0.10, "volatility": 0.30, "asset_class": "Equity", "liquidity_score": 80},
                {"ticker": "CASH", "weight": 0.02, "expected_return": 0.03, "volatility": 0.01, "asset_class": "Cash", "liquidity_score": 100},
            ]
        }
        review = review_portfolio(book, PortfolioMandate(max_position_pct=25, min_cash_pct=5))
        self.assertEqual(review.status, "breach")
        self.assertGreaterEqual(len(review.breaches), 2)
        self.assertEqual(len(review.scenarios), 4)
        self.assertTrue(review.risk_contributions)
        self.assertIn("simulation", review.metrics)
        self.assertEqual(review.metrics["simulation"]["paths"], 10_000)

    def test_committee_emits_auditable_interactions(self) -> None:
        context = QuantContext(
            "TEST",
            price_frame(),
            portfolio={"holdings": [{"ticker": "TEST", "weight": 0.35, "volatility": 0.25, "asset_class": "Equity"}]},
            strategy={"rule": "Moving-average trend", "trials_declared": 2},
        )
        run = CommitteeOrchestrator(
            default_organization(),
            ProviderSettings(provider="Deterministic", model="deterministic"),
            "",
            build_default_registry(),
        ).run("Teste la stratégie et son impact sur le portefeuille", context)
        kinds = {event.kind for event in run.interactions}
        self.assertTrue({"dispatch", "tool_call", "report", "synthesis"}.issubset(kinds))
        self.assertTrue({"challenge", "support"}.intersection(kinds))
        self.assertEqual(run.plan.request_kind, RequestKind.STRATEGY_TEST.value)
        self.assertEqual(len(run.reports), 8)
        html = workflow_graph_html(default_organization(), run)
        self.assertIn("VERIFIED INTERACTIONS", html)
        self.assertIn("STRATEGY BACKTEST", html)
        payload = workflow_payload(default_organization(), run)
        node_ids = {node["id"] for node in payload["nodes"]}
        self.assertTrue({"cio", "human_ic", "risk_manager", "strategy_backtest"}.issubset(node_ids))
        self.assertGreater(len(payload["edges"]), 20)
        quality = evaluate_committee(run, default_organization())
        self.assertGreaterEqual(quality.score, 50)
        self.assertEqual(len(quality.dimensions), 6)
        packet = decision_packet_json(run, default_organization(), quality)
        memo = decision_packet_markdown(run, default_organization(), quality)
        self.assertIn(run.run_id, packet)
        self.assertIn("Governance notice", memo)

    def test_organization_round_trip_preserves_customization_without_secrets(self) -> None:
        organization = default_organization()
        organization.name = "Client Sovereign Lab"
        organization.agents[0].mandate += "\nCLIENT POLICY: cite liquidity tier."
        restored = OrganizationConfig.from_dict(organization.to_dict())
        self.assertEqual(restored.name, organization.name)
        self.assertEqual(restored.agents[0].mandate, organization.agents[0].mandate)
        self.assertNotIn("api_key", restored.to_dict())


if __name__ == "__main__":
    unittest.main()

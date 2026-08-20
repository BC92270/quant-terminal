from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ProviderSettings
from .schemas import CommitteePlan, PlanStep, RequestKind


class ProviderError(RuntimeError):
    pass


def classify_request(query: str) -> RequestKind:
    text = query.lower()
    if any(word in text for word in ("backtest", "stratégie", "strategie", "strategy", "signal", "walk-forward", "alpha factor", "paper trade")):
        return RequestKind.STRATEGY_TEST
    if any(word in text for word in ("rebalance", "rééquilibr", "reequilibr", "réallou", "reallou")):
        return RequestKind.REBALANCE
    if any(word in text for word in ("portefeuille", "portfolio", "allocation", "book", "holdings", "positions")):
        return RequestKind.PORTFOLIO_REVIEW
    if any(word in text for word in ("hedge", "couverture", "protéger", "proteger", "option structure", "tail hedge")):
        return RequestKind.HEDGE_DESIGN
    if any(word in text for word in ("scenario", "scénario", "stress", "what if", "si la fed", "si les taux")):
        return RequestKind.SCENARIO_ANALYSIS
    if any(word in text for word in ("risque", "risk", "drawdown", "var", "cvar", "liquidité", "liquidity")):
        return RequestKind.RISK_REVIEW
    if any(word in text for word in ("screen", "classement", "universe", "univers", "compare", "comparatif", "top ")):
        return RequestKind.SCREENING
    if any(word in text for word in ("analyse", "analyze", "thèse", "thesis", "valorisation", "valuation", "earnings")):
        return RequestKind.SECURITY_RESEARCH
    return RequestKind.GENERAL


def deterministic_plan(
    query: str,
    ticker: str,
    available_tools: list[str],
    portfolio_available: bool = False,
) -> CommitteePlan:
    text = query.lower()
    request_kind = classify_request(query)
    tools = set(available_tools)
    desired: dict[str, tuple[list[str], str, str]] = {
        "quant_pm": (
            ["market_snapshot", "technical_regime", "risk_snapshot", "correlation_context", "monte_carlo_context", "strategy_backtest", "backtest_context", "ml_research_context"],
            "Test the market, statistical and model evidence.",
            "Every investment question requires a quantified base case.",
        )
    }
    if any(word in text for word in ("risque", "risk", "drawdown", "var", "tail", "stress", "perte", "hedge", "couverture")):
        desired["risk_manager"] = (
            ["risk_snapshot", "portfolio_diagnostics", "portfolio_context", "correlation_context", "derivatives_context", "event_intelligence", "strategy_backtest"],
            "Challenge downside, concentration, liquidity and tail scenarios.",
            "The question explicitly contains a risk or protection dimension.",
        )
    if portfolio_available or any(word in text for word in ("portfolio", "portefeuille", "allocation", "position", "sizing", "exposure", "book")):
        desired["portfolio_pm"] = (
            ["portfolio_diagnostics", "portfolio_context", "risk_snapshot", "correlation_context", "market_snapshot", "fixed_income_context", "execution_context"],
            "Translate the thesis into portfolio impact and sizing constraints.",
            "The request touches the existing book or implementation.",
        )
    if any(word in text for word in ("macro", "fed", "ecb", "bce", "rate", "taux", "inflation", "gdp", "currency", "fx", "oil", "gold", "géopolit", "geopolit")):
        desired["macro_strategist"] = (
            ["macro_context", "fixed_income_context", "event_intelligence", "market_snapshot"],
            "Map macro regime and cross-asset transmission channels.",
            "The request depends on macro or geopolitical conditions.",
        )
    if any(word in text for word in ("option", "future", "volatil", "volatility", "convex", "gamma", "hedge", "couverture", "skew")):
        desired["derivatives_strategist"] = (
            ["derivatives_context", "risk_snapshot", "market_snapshot", "monte_carlo_context"],
            "Evaluate volatility, convexity and hedge structures.",
            "The request has an explicit derivatives or convexity dimension.",
        )
    if request_kind == RequestKind.STRATEGY_TEST:
        desired["strategy_pm"] = (
            ["strategy_backtest", "market_snapshot", "technical_regime", "risk_snapshot", "backtest_context", "ml_research_context", "execution_context"],
            "Specify, reproduce and validate the strategy with realistic research gates.",
            "The request asks for a strategy test, signal or systematic validation.",
        )
    if request_kind in {RequestKind.STRATEGY_TEST, RequestKind.REBALANCE, RequestKind.HEDGE_DESIGN, RequestKind.PORTFOLIO_REVIEW} or any(
        word in text for word in ("execution", "liquidité", "liquidity", "slippage", "spread", "capacity", "market impact")
    ):
        desired["execution_trader"] = (
            ["execution_context", "market_snapshot", "risk_snapshot", "derivatives_context", "portfolio_diagnostics"],
            "Assess executable implementation, capacity, costs and operational constraints.",
            "The request can change exposure and therefore requires an execution feasibility check.",
        )
    if any(word in text for word in ("company", "société", "entreprise", "earnings", "résultat", "valuation", "fundamental", "secteur", "thèse", "thesis")) or ticker:
        desired["fundamental_research"] = (
            ["company_intelligence", "event_intelligence", "market_snapshot", "behavioral_context"],
            "Validate company, catalyst and thematic evidence.",
            "Ticker-level decisions require a fundamental and catalyst view.",
        )

    steps: list[PlanStep] = []
    required: list[str] = ["section_inventory"] if "section_inventory" in tools else []
    for specialist, (candidate_tools, objective, reason) in desired.items():
        selected = [name for name in candidate_tools if name in tools]
        required.extend(selected)
        steps.append(PlanStep(specialist, selected, objective, reason))
    ordered_tools = list(dict.fromkeys(required))
    return CommitteePlan(
        query=query,
        ticker=ticker,
        steps=steps,
        required_tools=ordered_tools,
        coverage=[step.specialist for step in steps],
        request_kind=request_kind.value,
    )


def parse_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("The model did not return a JSON object.")
        try:
            value = json.loads(clean[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"The model response is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProviderError("The model response must be a JSON object.")
    return value


class LLMClient:
    def __init__(self, settings: ProviderSettings, api_key: str) -> None:
        self.settings = settings
        self.api_key = api_key.strip()

    def complete(self, system_prompt: str, user_prompt: str, model_override: str = "") -> str:
        if not self.api_key:
            raise ProviderError("No session API key is connected.")
        provider = self.settings.provider.strip().lower()
        model = model_override if model_override and model_override != "inherit" else self.settings.model
        if provider == "openai":
            return self._openai_responses(system_prompt, user_prompt, model)
        if provider == "anthropic":
            return self._anthropic(system_prompt, user_prompt, model)
        if provider in {"google", "google gemini", "gemini"}:
            return self._gemini(system_prompt, user_prompt, model)
        return self._openai_compatible(system_prompt, user_prompt, model)

    def complete_json(self, system_prompt: str, user_prompt: str, model_override: str = "") -> dict[str, Any]:
        return parse_json_object(self.complete(system_prompt, user_prompt, model_override))

    def _request(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ProviderError(f"Provider HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Provider connection failed: {type(exc).__name__}: {exc}") from exc
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderError("Provider returned a non-JSON response.") from exc
        if not isinstance(value, dict):
            raise ProviderError("Provider returned an unexpected response envelope.")
        return value

    def _openai_responses(self, system: str, user: str, model: str) -> str:
        base = (self.settings.base_url or "https://api.openai.com/v1").rstrip("/")
        payload = {
            "model": model,
            "instructions": system,
            "input": user,
            "max_output_tokens": self.settings.max_output_tokens,
        }
        response = self._request(f"{base}/responses", payload, {"Authorization": f"Bearer {self.api_key}"})
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        parts: list[str] = []
        for item in response.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        if not parts:
            raise ProviderError("OpenAI response did not contain text output.")
        return "\n".join(parts)

    def _openai_compatible(self, system: str, user: str, model: str) -> str:
        defaults = {
            "openrouter": "https://openrouter.ai/api/v1",
            "mistral": "https://api.mistral.ai/v1",
            "groq": "https://api.groq.com/openai/v1",
        }
        provider = self.settings.provider.strip().lower()
        base = (self.settings.base_url or defaults.get(provider, "")).rstrip("/")
        if not base:
            raise ProviderError("A base URL is required for this OpenAI-compatible provider.")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
        }
        response = self._request(f"{base}/chat/completions", payload, {"Authorization": f"Bearer {self.api_key}"})
        try:
            return str(response["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI-compatible response did not contain message content.") from exc

    def _anthropic(self, system: str, user: str, model: str) -> str:
        base = (self.settings.base_url or "https://api.anthropic.com").rstrip("/")
        payload = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": self.settings.max_output_tokens,
            "temperature": self.settings.temperature,
        }
        response = self._request(
            f"{base}/v1/messages",
            payload,
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        parts = [item.get("text", "") for item in response.get("content", []) if isinstance(item, dict)]
        if not any(parts):
            raise ProviderError("Anthropic response did not contain text output.")
        return "\n".join(parts)

    def _gemini(self, system: str, user: str, model: str) -> str:
        base = (self.settings.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.settings.temperature,
                "maxOutputTokens": self.settings.max_output_tokens,
            },
        }
        response = self._request(f"{base}/models/{model}:generateContent?key={self.api_key}", payload, {})
        try:
            parts = response["candidates"][0]["content"]["parts"]
            return "\n".join(str(item.get("text", "")) for item in parts if isinstance(item, dict))
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Gemini response did not contain text output.") from exc

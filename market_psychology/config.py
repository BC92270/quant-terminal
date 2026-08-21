from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TRADING_DAYS: Final[int] = 252
DEFAULT_SYMBOL: Final[str] = "SPY"
DEFAULT_LOOKBACK: Final[str] = "2y"
DEFAULT_BENCHMARKS: Final[tuple[str, ...]] = (
    "SPY", "QQQ", "IWM", "HYG", "TLT", "GLD", "^VIX",
)

POSITIVE_WORDS: Final[set[str]] = {
    "beat", "beats", "growth", "upgrade", "upgrades", "strong", "record",
    "bullish", "surge", "surges", "rally", "rallies", "optimism", "optimistic",
    "accelerate", "accelerates", "acceleration", "outperform", "outperforms",
    "expansion", "expands", "rebound", "recovery", "profit", "profits",
    "demand", "innovation", "breakthrough", "approval", "approved",
}

NEGATIVE_WORDS: Final[set[str]] = {
    "miss", "misses", "warning", "warnings", "downgrade", "downgrades", "weak",
    "bearish", "drop", "drops", "selloff", "sell-off", "crash", "fear", "panic",
    "recession", "slowdown", "decline", "declines", "loss", "losses", "fraud",
    "probe", "investigation", "default", "bankruptcy", "layoff", "layoffs",
    "risk", "risks", "uncertainty", "uncertain", "stress", "stressed",
}

UNCERTAINTY_WORDS: Final[set[str]] = {
    "uncertainty", "uncertain", "risk", "risks", "could", "may", "might",
    "volatile", "volatility", "unknown", "unclear", "concern", "concerns",
    "question", "questions", "mixed", "debate", "doubt", "doubts",
}

NARRATIVE_THEMES: Final[dict[str, tuple[str, ...]]] = {
    "AI / semiconductors": ("ai", "artificial intelligence", "chip", "chips", "semiconductor", "gpu", "data center", "datacenter"),
    "Rates / Fed": ("fed", "federal reserve", "rate", "rates", "yield", "yields", "powell", "cut", "cuts", "hike", "hikes"),
    "Inflation": ("inflation", "cpi", "pce", "prices", "disinflation"),
    "Growth / recession": ("growth", "recession", "slowdown", "gdp", "soft landing", "hard landing"),
    "Earnings": ("earnings", "revenue", "profit", "guidance", "eps", "margin", "margins"),
    "Liquidity / leverage": ("liquidity", "leverage", "margin", "funding", "credit", "spread", "spreads"),
    "Geopolitics": ("war", "sanction", "sanctions", "geopolitical", "conflict", "tariff", "tariffs", "china", "russia", "iran"),
    "Crypto / speculative": ("bitcoin", "crypto", "token", "meme", "short squeeze", "squeeze", "retail"),
}


@dataclass(frozen=True)
class MechanismSpec:
    key: str
    label: str
    layer: str
    scientific_status: str
    description: str


MECHANISM_SPECS: Final[tuple[MechanismSpec, ...]] = (
    MechanismSpec("attention", "Attention", "Cognition", "Core", "Concentration anormale de l'attention sur le marché ou le titre."),
    MechanismSpec("salience", "Salience", "Cognition", "Core", "Poids cognitif disproportionné des mouvements extrêmes/récents."),
    MechanismSpec("memory", "Memory / analogues", "Cognition", "Core experimental", "Réactivation d'épisodes historiques ressemblant au contexte présent."),
    MechanismSpec("experience", "Experience effects", "Cognition", "Research / unobserved", "Effets de cohortes et d'expériences vécues; non identifiables sans données investisseurs/cohortes."),
    MechanismSpec("information_processing", "Information redundancy", "Cognition", "Core experimental", "Risque qu'un même facteur latent soit traité comme plusieurs confirmations indépendantes."),
    MechanismSpec("extrapolation", "Extrapolation", "Cognition", "Core", "Degré auquel les tendances récentes semblent être prolongées dans les comportements."),
    MechanismSpec("mental_model", "Mental model", "Cognition", "Experimental", "Dominance d'une lecture momentum, fundamental, macro, flow ou narrative."),
    MechanismSpec("confidence", "Belief confidence", "Beliefs", "Core experimental", "Force/cohérence des signaux malgré le bruit et la dispersion."),
    MechanismSpec("disagreement", "Disagreement", "Beliefs", "Core", "Dispersion des signaux cross-asset, news et options."),
    MechanismSpec("higher_order", "Higher-order beliefs", "Beliefs", "Experimental", "Proxy d'optimisme sur ce que les autres investisseurs pourraient croire/acheter."),
    MechanismSpec("ambiguity", "Ambiguity", "Beliefs", "Core", "Incertitude sur le modèle lui-même, distincte du risque mesurable."),
    MechanismSpec("fear", "Fear / negative affect", "Preference / affect", "Core", "État affectif négatif inféré via downside, vol, options et langage."),
    MechanismSpec("risk_appetite", "Risk appetite", "Preference / affect", "Core", "Préférence observable pour actifs risqués vs défensifs."),
    MechanismSpec("lottery_demand", "Lottery demand", "Preference / affect", "Core experimental", "Demande pour convexité / upside asymétrique et calls courts."),
    MechanismSpec("narrative", "Narrative concentration", "Social / reflexive", "Core", "Concentration et persistance des thèmes dominants dans le flux textuel."),
    MechanismSpec("herding", "Herding / synchronization", "Social / reflexive", "Core", "Synchronisation cross-sectionnelle et réduction de la dispersion indépendante."),
    MechanismSpec("social_contagion", "Social contagion", "Social / reflexive", "Experimental", "Propagation rapide de signaux communs; proxy faute de graphe social complet."),
    MechanismSpec("reflexivity", "Psychological reflexivity", "Social / reflexive", "Core experimental", "Boucle prix → attention/flux → prix."),
    MechanismSpec("mechanical_reflexivity", "Mechanical reflexivity", "Constraints", "Structural proxy", "Amplification mécanique via vol/liquidité/options; dealer gamma réel non identifié sans feed."),
    MechanismSpec("arbitrage_capacity", "Arbitrage capacity", "Constraints", "Structural proxy", "Capacité estimée du marché à absorber/corriger les pressions comportementales."),
)

REGIME_LABELS: Final[tuple[str, ...]] = (
    "RATIONAL CONSENSUS",
    "CAUTIOUS ACCUMULATION",
    "EXTRAPOLATIVE EXPANSION",
    "NARRATIVE MANIA",
    "REFLEXIVE SPECULATIVE EXPANSION",
    "FRAGILE CONSENSUS",
    "BELIEF FRAGMENTATION",
    "FEAR CASCADE",
    "CAPITULATION",
    "POST-CAPITULATION",
    "MIXED / UNIDENTIFIED",
)

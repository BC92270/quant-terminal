from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


ONTOLOGY_VERSION = "2.5.0"


@dataclass(frozen=True)
class MechanismDefinition:
    family: str
    aliases: tuple[str, ...]
    description: str = ""


# Mechanisms are domain-agnostic on purpose.  The aliases are conservative lexical
# anchors, not proof that the mechanism is scientifically present.
MECHANISM_ONTOLOGY: dict[str, MechanismDefinition] = {
    "criticality": MechanismDefinition("DYNAMICS", ("criticality", "critical transition", "critical point", "tipping point", "critical slowing down")),
    "threshold": MechanismDefinition("DYNAMICS", ("threshold", "critical boundary", "trigger level", "event horizon")),
    "feedback": MechanismDefinition("DYNAMICS", ("feedback", "self-reinforcing", "positive feedback", "negative feedback", "feedback loop")),
    "bifurcation": MechanismDefinition("DYNAMICS", ("bifurcation", "regime shift", "regime transition", "loss of stability")),
    "regime_switching": MechanismDefinition("DYNAMICS", ("regime switching", "regime-switching", "switching regime", "regime switches", "regime switch")),
    "change_point_detection": MechanismDefinition("DYNAMICS", ("change point", "change-point", "cusum", "cumulative sum control chart")),
    "heavy_tails": MechanismDefinition("DISTRIBUTION", ("heavy tails", "heavy-tailed", "heavy tailed", "fat tails", "fat-tailed")),
    "online_adaptation": MechanismDefinition("ADAPTATION", ("keep model parameters up to date", "update model parameters", "parameter updating", "online updating", "online adaptation")),
    "attractor": MechanismDefinition("DYNAMICS", ("attractor", "basin of attraction", "potential well", "trapping region", "trapping surface")),
    "oscillation": MechanismDefinition("DYNAMICS", ("oscillation", "oscillator", "limit cycle", "periodic dynamics")),
    "synchronization": MechanismDefinition("DYNAMICS", ("synchronization", "synchronisation", "coupled oscillators", "phase locking", "coherence")),
    "self_organization": MechanismDefinition("DYNAMICS", ("self-organization", "self organization", "emergent order", "collective organization")),
    "multiscale": MechanismDefinition("SCALE", ("multiscale", "multi-scale", "scaling law", "scale invariant", "scale-invariant", "fractal", "multifractal")),
    "renormalization": MechanismDefinition("SCALE", ("renormalization", "renormalisation", "renormalization group", "coarse graining")),
    "intermittency": MechanismDefinition("SCALE", ("intermittency", "intermittent dynamics", "burstiness")),
    "turbulence": MechanismDefinition("SCALE", ("turbulence", "turbulent", "energy cascade", "cascade across scales")),
    "network": MechanismDefinition("NETWORK", ("network", "graph", "node", "edge", "connectivity", "network topology")),
    "contagion": MechanismDefinition("NETWORK", ("contagion", "spillover", "transmission", "shock propagation", "cascade failure", "cascading failure")),
    "percolation": MechanismDefinition("NETWORK", ("percolation", "percolation threshold", "giant component")),
    "centrality": MechanismDefinition("NETWORK", ("centrality", "betweenness", "eigenvector centrality", "pagerank")),
    "community_structure": MechanismDefinition("NETWORK", ("community structure", "community detection", "modularity", "cluster structure")),
    "diffusion": MechanismDefinition("TRANSPORT", ("diffusion", "diffusive", "transport process", "propagation process", "reaction-diffusion")),
    "flow": MechanismDefinition("TRANSPORT", ("flow", "flux", "transport", "advection")),
    "entropy": MechanismDefinition("INFORMATION", ("entropy", "entropy rate", "information entropy", "information disorder")),
    "mutual_information": MechanismDefinition("INFORMATION", ("mutual information", "conditional mutual information")),
    "information_flow": MechanismDefinition("INFORMATION", ("information flow", "transfer entropy", "information transfer")),
    "information_geometry": MechanismDefinition("INFORMATION", ("information geometry", "fisher information", "fisher metric")),
    "geometry": MechanismDefinition("GEOMETRY", ("curvature", "ricci curvature", "metric tensor", "geodesic", "manifold", "differential geometry")),
    "topology": MechanismDefinition("GEOMETRY", ("topology", "persistent homology", "betti number", "simplicial complex", "topological data analysis")),
    "symmetry": MechanismDefinition("GEOMETRY", ("symmetry", "symmetry breaking", "invariance", "invariant")),
    "conservation": MechanismDefinition("PHYSICAL_STRUCTURE", ("conservation law", "conserved quantity", "mass conservation", "energy conservation", "momentum conservation")),
    "potential": MechanismDefinition("PHYSICAL_STRUCTURE", ("potential energy", "potential function", "energy landscape", "potential landscape")),
    "stochasticity": MechanismDefinition("STOCHASTIC", ("stochastic", "brownian motion", "random process", "diffusion process", "ito process", "itô process", "levy process", "lévy process", "levy-driven", "lévy-driven")),
    "memory": MechanismDefinition("STOCHASTIC", ("long memory", "memory effect", "non-markovian", "non markovian", "path dependence", "path-dependent")),
    "mean_field": MechanismDefinition("INTERACTION", ("mean field", "mean-field", "mean field game", "mean-field game")),
    "interaction": MechanismDefinition("INTERACTION", ("interaction", "coupling", "pairwise interaction", "agent interaction")),
    "competition": MechanismDefinition("ADAPTATION", ("competition", "competitive dynamics", "predator-prey", "predator prey")),
    "selection": MechanismDefinition("ADAPTATION", ("selection", "natural selection", "strategy selection")),
    "adaptation": MechanismDefinition("ADAPTATION", ("adaptation", "adaptive", "evolutionary dynamics", "evolutionary")),
    "herding": MechanismDefinition("BEHAVIOR", ("herding", "herd behavior", "herd behaviour", "imitation", "social imitation")),
    "optimization": MechanismDefinition("OPTIMIZATION", ("optimization", "optimisation", "optimal solution", "objective function", "argmin", "argmax")),
    "control": MechanismDefinition("CONTROL", ("control theory", "stochastic control", "optimal control", "controller", "feedback control")),
    "causality": MechanismDefinition("CAUSAL", ("causal", "causality", "causal inference", "granger causality")),
    "robustness": MechanismDefinition("ROBUSTNESS", ("robustness", "resilience", "stability margin", "robust control")),
    "spectral_structure": MechanismDefinition("SPECTRAL", ("eigenvalue spectrum", "spectral density", "spectral analysis", "largest eigenvalue", "eigenvalue distribution", "marčenko-pastur", "marchenko-pastur")),
    "covariance_structure": MechanismDefinition("SPECTRAL", ("covariance matrix", "correlation matrix", "covariance estimation", "correlation structure", "matrix cleaning")),
    "random_matrix": MechanismDefinition("SPECTRAL", ("random matrix theory", "random matrix", "rmt", "free probability", "matrix freeness")),
}


# Canonical source-grounded entities. These patterns only create a record when the
# literal source text contains a matching alias.
SEMANTIC_ENTITY_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "Theory": {
        "Random Matrix Theory": ("random matrix theory", "rmt"),
        "Free Probability": ("free probability",),
        "Rough Path Theory": ("rough path theory", "rough paths"),
        "Rough Volatility": ("rough volatility",),
        "Optimal Transport": ("optimal transport",),
        "Martingale Optimal Transport": ("martingale optimal transport",),
        "Information Theory": ("information theory",),
        "Control Theory": ("control theory",),
        "Mean Field Games": ("mean field games", "mean-field games", "mean field game"),
        "Percolation Theory": ("percolation theory",),
        "Statistical Mechanics": ("statistical mechanics",),
        "General Relativity": ("general relativity",),
    },
    "Method": {
        "Principal Component Analysis": ("principal component analysis", "pca"),
        "Singular Value Decomposition": ("singular value decomposition", "svd"),
        "Random Singular Value Decomposition": ("random singular value decomposition",),
        "Monte Carlo": ("monte carlo",),
        "Bootstrap": ("bootstrap", "bootstrapping"),
        "Maximum Likelihood": ("maximum likelihood",),
        "Bayesian Inference": ("bayesian inference", "bayesian estimation"),
        "Regression": ("regression",),
        "Persistent Homology": ("persistent homology",),
        "Community Detection": ("community detection",),
        "Hidden Markov Model": ("hidden markov model", "hmm"),
        "CUSUM": ("cusum", "cumulative sum control chart"),
        "Ordinary Least Squares": ("ordinary least squares", "ols"),
        "Regularized Least Squares": ("regularized least squares", "regularised least squares", "rls"),
    },
    "MathematicalObject": {
        "Correlation Matrix": ("correlation matrix", "correlation matrices"),
        "Covariance Matrix": ("covariance matrix", "covariance matrices"),
        "Eigenvalue Spectrum": ("eigenvalue spectrum", "spectrum of eigenvalues", "bulk density of states"),
        "Marcenko-Pastur Spectrum": ("marčenko-pastur spectrum", "marchenko-pastur spectrum", "marcenko-pastur spectrum"),
        "Random Matrix": ("random matrix", "random matrices"),
        "Rectangular Correlation Matrix": ("rectangular correlation matrix", "rectangular correlation matrices"),
        "Graph": ("graph", "graphs"),
        "Network": ("network", "networks"),
        "Metric Tensor": ("metric tensor",),
        "Ricci Curvature": ("ricci curvature",),
        "Geodesic": ("geodesic", "geodesics"),
        "Stochastic Process": ("stochastic process", "stochastic processes"),
        "Brownian Motion": ("brownian motion",),
        "Martingale": ("martingale", "martingales"),
        "Ornstein-Uhlenbeck Process": ("ornstein-uhlenbeck process", "ornstein–uhlenbeck process", "ornstein uhlenbeck process"),
        "Levy Process": ("levy process", "lévy process", "levy-driven", "lévy-driven"),
    },
    "Concept": {
        "Largest Eigenvalue Statistics": ("largest eigenvalue statistics", "largest eigenvalue"),
        "Matrix Freeness": ("matrix freeness", "free matrices"),
        "Out-of-Sample Generalization": ("out-of-sample", "out of sample"),
        "Noise Filtering": ("noise filtering", "eigenvalue cleaning", "matrix cleaning"),
        "Scale Invariance": ("scale invariance", "scale-invariant", "scale invariant"),
        "Critical Slowing Down": ("critical slowing down",),
        "Phase Transition": ("phase transition", "phase transitions"),
        "Regime Transition": ("regime transition", "regime shift"),
        "Regime Switching": ("regime switching", "regime-switching", "regime switches", "regime switch"),
        "Heavy Tails": ("heavy tails", "heavy-tailed", "heavy tailed", "fat tails"),
    },
    "Application": {
        "Portfolio Optimization": ("portfolio optimization", "portfolio optimisation"),
        "Risk Estimation": ("risk estimation",),
        "Out-of-Sample Risk Estimation": ("out-of-sample risk estimation", "out of sample risk estimation"),
        "Systemic Risk": ("systemic risk",),
        "Option Pricing": ("option pricing",),
        "Asset Pricing": ("asset pricing",),
        "Bubble Detection": ("bubble detection", "financial bubbles", "speculative bubbles"),
        "Regime Detection": ("regime detection", "regime classification", "detecting regime changes", "determining regime switches"),
        "Online Regime Detection": ("online regime detection", "regime switches consecutively as they happen online"),
        "Market Microstructure": ("market microstructure",),
    },
}


FINANCE_INTENT_TERMS: tuple[str, ...] = (
    "finance", "financial", "market", "markets", "portfolio", "asset", "assets", "risk",
    "volatility", "trading", "option", "options", "equity", "equities", "credit", "liquidity",
    "bubble", "bubbles", "systemic", "returns", "correlation", "covariance",
)

SCIENTIFIC_SIGNAL_TERMS: tuple[str, ...] = tuple(sorted({
    "theory", "model", "equation", "stochastic", "matrix", "network", "geometry", "topology",
    "physics", "statistical", "probability", "algorithm", "dynamics", "critical", "diffusion",
    "entropy", "optimization", "control", "eigenvalue", "spectrum", "tensor", "curvature",
    "multiscale", "causal", "simulation", "inference", "estimation", "graph",
}))


def mechanism_family(mechanism: str) -> str:
    definition = MECHANISM_ONTOLOGY.get(str(mechanism))
    return definition.family if definition else "OTHER"


def mechanism_aliases(mechanism: str) -> tuple[str, ...]:
    definition = MECHANISM_ONTOLOGY.get(str(mechanism))
    return definition.aliases if definition else (str(mechanism).replace("_", " "),)


def _phrase_hits(lower_text: str, phrase: str) -> int:
    phrase = str(phrase or "").strip().lower()
    if not phrase:
        return 0
    if len(phrase) <= 3 and phrase.isalpha():
        return len(re.findall(rf"\b{re.escape(phrase)}\b", lower_text, flags=re.IGNORECASE))
    return lower_text.count(phrase)


def extract_mechanism_scores(text: str) -> dict[str, float]:
    lower = str(text or "").lower()
    scored: dict[str, float] = {}
    for mechanism, definition in MECHANISM_ONTOLOGY.items():
        hits = sum(_phrase_hits(lower, alias) for alias in definition.aliases)
        if hits:
            # Score is parser salience only, deliberately not a probability.
            scored[mechanism] = round(min(1.0, 0.34 + 0.16 * hits), 3)
    return dict(sorted(scored.items(), key=lambda item: (-item[1], item[0])))


def iter_entity_aliases() -> Iterable[tuple[str, str, tuple[str, ...]]]:
    for entity_type, entities in SEMANTIC_ENTITY_PATTERNS.items():
        for canonical, aliases in entities.items():
            yield entity_type, canonical, aliases

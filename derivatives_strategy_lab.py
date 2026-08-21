"""Institutional-style options strategy construction and risk analytics.

The module deliberately separates pure quantitative functions from Streamlit
rendering so payoff, pricing and Greek conventions can be regression-tested.
Market quotes remain indicative when the caller supplies delayed/public data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


CONTRACT_MULTIPLIER = 100.0
TRADING_DAYS = 252.0
CALENDAR_DAYS = 365.0
EPS = 1e-12
NORMAL = NormalDist()


@dataclass(frozen=True)
class StrategyLeg:
    """One option or stock leg. Premiums and IVs are per share / decimal."""

    instrument: str
    side: int
    quantity: int
    strike: float = 0.0
    premium: float = 0.0
    iv: float = 0.0
    dte: int = 0
    bid: float = 0.0
    ask: float = 0.0
    label: str = ""

    @property
    def multiplier(self) -> float:
        return 1.0 if self.instrument == "stock" else CONTRACT_MULTIPLIER

    @property
    def signed_units(self) -> float:
        return float(self.side * self.quantity) * self.multiplier


@dataclass(frozen=True)
class StrategySummary:
    net_debit: float
    max_profit: float
    max_loss: float
    break_evens: Tuple[float, ...]
    probability_of_profit: Optional[float]
    expected_pnl: Optional[float]
    reward_to_risk: Optional[float]
    capital_at_risk: float
    right_tail: str


STRATEGY_TEMPLATES: Tuple[str, ...] = (
    "Long Call",
    "Long Put",
    "Bull Call Spread",
    "Bear Put Spread",
    "Covered Call",
    "Protective Put",
    "Collar",
    "Long Straddle",
    "Long Strangle",
    "Short Strangle",
    "Call Butterfly",
    "Broken-Wing Butterfly",
    "Iron Butterfly",
    "Iron Condor",
    "Risk Reversal",
)


STRATEGY_PROFILES: Dict[str, Dict[str, Any]] = {
    "Long Call": {"direction": 1.0, "vol": 1.0, "complexity": 1, "thesis": "Hausse convexe, perte limitée."},
    "Long Put": {"direction": -1.0, "vol": 1.0, "complexity": 1, "thesis": "Baisse convexe ou couverture."},
    "Bull Call Spread": {"direction": 0.8, "vol": 0.2, "complexity": 2, "thesis": "Hausse ciblée avec budget borné."},
    "Bear Put Spread": {"direction": -0.8, "vol": 0.2, "complexity": 2, "thesis": "Baisse ciblée avec risque borné."},
    "Covered Call": {"direction": 0.35, "vol": -0.6, "complexity": 2, "thesis": "Monétiser une hausse plafonnée."},
    "Protective Put": {"direction": 0.35, "vol": 0.7, "complexity": 2, "thesis": "Conserver le sous-jacent avec plancher."},
    "Collar": {"direction": 0.2, "vol": -0.1, "complexity": 3, "thesis": "Encadrer une position action."},
    "Long Straddle": {"direction": 0.0, "vol": 1.0, "complexity": 2, "thesis": "Acheter un mouvement absolu."},
    "Long Strangle": {"direction": 0.0, "vol": 0.85, "complexity": 2, "thesis": "Convexité moins chère, seuils plus éloignés."},
    "Short Strangle": {"direction": 0.0, "vol": -1.0, "complexity": 3, "thesis": "Vendre la plage, risque de queue non borné."},
    "Call Butterfly": {"direction": 0.15, "vol": -0.6, "complexity": 3, "thesis": "Cibler un niveau d'expiration précis."},
    "Broken-Wing Butterfly": {"direction": 0.3, "vol": -0.45, "complexity": 4, "thesis": "Cibler un niveau avec asymétrie contrôlée."},
    "Iron Butterfly": {"direction": 0.0, "vol": -0.9, "complexity": 4, "thesis": "Vendre le mouvement avec ailes de protection."},
    "Iron Condor": {"direction": 0.0, "vol": -0.75, "complexity": 4, "thesis": "Vendre une plage bornée."},
    "Risk Reversal": {"direction": 0.9, "vol": 0.0, "complexity": 2, "thesis": "Exposition directionnelle financée par le skew."},
}


GREEK_REFERENCE = pd.DataFrame(
    [
        {"Greek": "Delta", "Définition": "∂V/∂S", "Unité live": "$ d'option / $ de spot", "Décision": "Direction et hedge local", "Limite": "Change avec spot, temps et IV"},
        {"Greek": "Gamma", "Définition": "∂²V/∂S² = ∂Δ/∂S", "Unité live": "Delta / $", "Décision": "Convexité et fréquence de re-hedge", "Limite": "Explose près du strike à court DTE"},
        {"Greek": "Vega", "Définition": "∂V/∂σ", "Unité live": "$ / +1 vol pt", "Décision": "Risque d'expansion/compression IV", "Limite": "Dépend de la surface, pas d'une IV plate"},
        {"Greek": "Theta", "Définition": "Variation pour 1 jour écoulé", "Unité live": "$ / jour", "Décision": "Carry temporel", "Limite": "Non linéaire, surtout proche échéance"},
        {"Greek": "Rho", "Définition": "∂V/∂r", "Unité live": "$ / +100 bps", "Décision": "Sensibilité taux/forward", "Limite": "Secondaire en court terme, important en LEAPS"},
        {"Greek": "Vanna", "Définition": "∂Δ/∂σ = ∂Vega/∂S", "Unité live": "Delta / +1 vol pt", "Décision": "Drift du hedge sous choc IV", "Limite": "Très dépendant du smile dynamique"},
        {"Greek": "Vomma", "Définition": "∂Vega/∂σ", "Unité live": "$ / (1 vol pt)²", "Décision": "Convexité à la volatilité", "Limite": "Convention d'échelle souvent ambiguë"},
        {"Greek": "Charm", "Définition": "Variation du delta en 1 jour", "Unité live": "Delta / jour", "Décision": "Hedge drift / pin risk", "Limite": "Sensible au calendrier exact"},
        {"Greek": "Speed", "Définition": "∂Gamma/∂S", "Unité live": "Gamma / $", "Décision": "Instabilité de la convexité", "Limite": "Bruit élevé près expiration"},
        {"Greek": "Color", "Définition": "Variation du gamma en 1 jour", "Unité live": "Gamma / jour", "Décision": "Évolution du risque de re-hedge", "Limite": "Convention de signe variable"},
        {"Greek": "Zomma", "Définition": "∂Gamma/∂σ", "Unité live": "Gamma / +1 vol pt", "Décision": "Gamma sous choc IV", "Limite": "Modèle local, smile non recalibré"},
    ]
)


GREEK_ANALYTICS: Dict[str, Dict[str, str]] = {
    "Delta": {
        "key": "delta",
        "formula": "Delta = ∂V/∂S",
        "unit": "actions équivalentes",
        "definition": "Sensibilité locale du prix de la position à une variation de 1 $ du sous-jacent.",
        "variants": "1) dérivée de prix ; 2) ratio de couverture ; 3) exposition directionnelle/cash delta. Delta est parfois utilisé comme proxy de probabilité, mais N(d₁) n'est pas N(d₂).",
        "drivers": "Spot, moneyness, temps, volatilité, dividendes et taux. Gamma, vanna et charm expliquent son évolution locale.",
        "positive": "Le book gagne localement si le spot monte ; couvrir en vendant environ le même nombre d'actions.",
        "negative": "Le book gagne localement si le spot baisse ; couvrir en achetant des actions.",
        "hedge": "Actions/futures pour le hedge instantané ; options ou spreads si l'objectif est aussi de modifier gamma et vega.",
        "structures": "Long call, short put et risk reversal créent du delta positif. Long put, short call et bear spread créent du delta négatif.",
        "caveat": "Un hedge delta est instantané : il dérive dès que spot, IV ou temps changent. Il ne neutralise ni gaps, ni gamma, ni basis futures.",
    },
    "Gamma": {
        "key": "dollar_gamma_1pct",
        "formula": "Gamma = ∂²V/∂S² = ∂Delta/∂S",
        "unit": "$ de P&L pour un mouvement spot de 1 %",
        "definition": "Convexité spot et vitesse de variation du delta. L'exposition affichée vaut ½Γ(1 % × spot)².",
        "variants": "Gamma brut mesure le changement de delta par dollar ; dollar gamma convertit cette courbure en P&L ; gamma cash/notional sert à agréger un portefeuille.",
        "drivers": "Maximum près de l'ATM et de l'expiration. Speed décrit sa variation avec le spot, color avec le temps et zomma avec l'IV.",
        "positive": "Convexité favorable aux mouvements et au re-hedging, généralement financée par un theta négatif.",
        "negative": "Carry souvent positif mais pertes accélérées lors d'un mouvement ; risque de gap et de hedge procyclique.",
        "hedge": "Réduire les options courtes proches ATM/court DTE, acheter des ailes ou du gamma ; le hedge en actions ne neutralise que le delta courant.",
        "structures": "Straddle/strangle longs et options longues sont gamma positifs. Strangle, butterfly et condor vendus sont souvent gamma négatifs près du corps.",
        "caveat": "Le gamma explose à très court DTE, tandis que le modèle continu sous-estime les gaps, suspensions et discontinuités de marché.",
    },
    "Vega": {
        "key": "vega_1vol",
        "formula": "Vega = ∂V/∂σ",
        "unit": "$ pour +1 point de volatilité",
        "definition": "Variation locale de valeur pour une hausse d'un point d'IV, toutes choses égales par ailleurs.",
        "variants": "Vega parallèle suppose toute la surface décalée. En production, on sépare vega par maturité, strike, facteur de niveau, skew et convexité.",
        "drivers": "Temps restant, spot, moneyness et niveau d'IV. Vanna relie vega au spot et vomma mesure sa convexité à l'IV.",
        "positive": "Bénéficie d'une expansion d'IV ; exposé à la prime payée, au crush post-événement et au theta.",
        "negative": "Bénéficie d'une compression d'IV ; porte un risque d'expansion, de skew et de queues.",
        "hedge": "Options de maturité/strike adaptés ; un hedge delta ne couvre pas le vega. Neutraliser aussi les facteurs de skew plutôt que le seul vega total.",
        "structures": "Straddle/strangle longs achètent du vega ; condor, butterfly et options couvertes en vendent selon la zone de spot.",
        "caveat": "Un choc d'IV parallèle est simplificateur : la surface se tord, les ailes bougent différemment et le vol-of-vol modifie la réponse.",
    },
    "Theta": {
        "key": "theta_1d",
        "formula": "Theta = ∂V/∂t",
        "unit": "$ pour un jour calendaire écoulé",
        "definition": "Carry temporel local si spot, IV, taux et surface restent inchangés.",
        "variants": "Theta calendaire, theta de trading day et carry réalisé diffèrent. Le P&L réel inclut mouvement spot, IV, financement et re-hedging.",
        "drivers": "DTE, moneyness, IV, calendrier événementiel et taux. La décroissance est fortement non linéaire près de l'expiration.",
        "positive": "Le passage du temps aide le book, mais le carry rémunère souvent une vente de gamma/vega ou un risque d'assignation.",
        "negative": "Le book paie pour convexité, assurance ou optionalité ; la thèse doit se réaliser assez vite.",
        "hedge": "Roller l'échéance, réduire les options longues coûteuses ou financer avec une jambe courte bornée ; contrôler le gamma sacrifié.",
        "structures": "Calendars et structures courtes bornées peuvent produire du theta positif ; options et straddles longs ont généralement un theta négatif.",
        "caveat": "Theta n'est pas un revenu certain. Un mouvement, un choc d'IV ou un gap peut dominer plusieurs jours de carry en quelques secondes.",
    },
    "Rho": {
        "key": "rho_100bp",
        "formula": "Rho = ∂V/∂r",
        "unit": "$ pour +100 points de base",
        "definition": "Sensibilité locale au taux sans risque, via actualisation et déplacement du forward.",
        "variants": "On distingue sensibilité au taux de financement, courbe par maturité, dividendes implicites et coût d'emprunt du sous-jacent.",
        "drivers": "Maturité, moneyness, niveau des taux, dividendes et borrow. L'effet devient important sur LEAPS et options sur futures.",
        "positive": "Une hausse des taux augmente localement la valeur du book ; fréquent sur calls longs et puts courts.",
        "negative": "Une hausse des taux pénalise localement le book ; fréquent sur puts longs et calls courts.",
        "hedge": "Options/forwards de même maturité et instruments de taux ; une seule hypothèse de taux plat ne couvre pas le risque de courbe.",
        "structures": "Calls longs tendent à être rho positifs, puts longs rho négatifs. Les spreads réduisent généralement l'exposition nette.",
        "caveat": "Le rho BSM confond parfois taux, forward, dividendes et borrow. Une courbe et des forwards observables sont requis en production.",
    },
    "Vanna": {
        "key": "vanna_1vol",
        "formula": "Vanna = ∂Delta/∂σ = ∂Vega/∂S",
        "unit": "delta pour +1 point de volatilité",
        "definition": "Interaction spot-vol : dérive du hedge delta lorsque l'IV change, ou variation du vega lorsque le spot bouge.",
        "variants": "La vanna locale BSM suppose une IV plate ; la vanna de surface inclut le mouvement du skew et dépend de la règle sticky-strike/sticky-delta.",
        "drivers": "Moneyness, DTE, skew, corrélation spot-vol et dynamique de surface. Elle change souvent de signe autour de l'ATM.",
        "positive": "Une hausse d'IV rend le delta plus positif ; anticiper une vente d'actions pour rester delta-neutre.",
        "negative": "Une hausse d'IV rend le delta plus négatif ; anticiper un achat d'actions pour rester delta-neutre.",
        "hedge": "Rebalancer delta sous scénarios d'IV et utiliser des options choisies par strike/maturité ; un simple vega hedge peut laisser la vanna intacte.",
        "structures": "Risk reversals et positions dans les ailes créent une vanna marquée ; structures symétriques ATM peuvent en réduire une partie.",
        "caveat": "Très dépendante du smile dynamique. Le chiffre BSM local peut inverser la lecture si la surface suit une autre convention.",
    },
    "Vomma": {
        "key": "vomma_1vol2",
        "formula": "Vomma (Volga) = ∂Vega/∂σ",
        "unit": "$ par (point de volatilité)²",
        "definition": "Convexité à la volatilité : variation du vega quand le niveau d'IV se déplace.",
        "variants": "Vomma/volga BSM est une dérivée locale. La convexité de surface et le vol-of-vol requièrent un modèle de smile ou stochastique.",
        "drivers": "Moneyness, temps, d₁/d₂ et niveau d'IV. Les ailes longues peuvent porter beaucoup de vomma pour peu de vega initial.",
        "positive": "Le vega augmente lors d'un choc d'IV dans le sens favorable ; bénéfice convexe aux grands déplacements de vol.",
        "negative": "La perte accélère sous grands chocs d'IV ; fréquent lorsqu'on vend les ailes ou une convexité de volatilité.",
        "hedge": "Options d'ailes et maturités différentes ; neutraliser seulement le vega au point courant ne neutralise pas le vomma.",
        "structures": "Strangles longs et options OTM longues sont souvent vomma positifs ; ratio spreads et ventes d'ailes peuvent être négatifs.",
        "caveat": "Les unités varient selon les systèmes. Ici le résultat est explicitement exprimé pour des points de vol, au carré.",
    },
    "Charm": {
        "key": "charm_1d",
        "formula": "Charm ≈ Delta(t + 1 jour) - Delta(t)",
        "unit": "delta par jour calendaire",
        "definition": "Dérive temporelle du delta à spot et IV constants ; indique le hedge à ajuster même si le marché ne bouge pas.",
        "variants": "Les conventions de signe diffèrent selon que t désigne le temps écoulé ou le temps restant. Ici, positif = delta plus positif demain.",
        "drivers": "DTE, moneyness, taux, dividendes et proximité d'un strike/pin. Très instable en dernière semaine.",
        "positive": "Le delta deviendra plus positif avec le temps ; vendre progressivement des actions pour maintenir la neutralité.",
        "negative": "Le delta deviendra plus négatif avec le temps ; acheter progressivement des actions pour maintenir la neutralité.",
        "hedge": "Planifier les rebalances calendaires, réduire les shorts proches du strike et surveiller pin/assignment à l'approche de l'échéance.",
        "structures": "Calendars, diagonals et books proches d'expiration peuvent concentrer le charm même avec un delta actuel faible.",
        "caveat": "Le week-end, les jours fériés et les conventions de calendrier changent la mesure. La surface réelle ne reste pas constante.",
    },
    "Speed": {
        "key": "speed",
        "formula": "Speed = ∂Gamma/∂S = ∂³V/∂S³",
        "unit": "gamma par dollar de spot",
        "definition": "Mesure à quelle vitesse le gamma change quand le sous-jacent se déplace.",
        "variants": "Speed brut, dollar speed et speed normalisé répondent à des usages différents de comparaison et de limite de risque.",
        "drivers": "Moneyness, très court DTE et IV. Le speed est extrême lorsque le spot traverse rapidement une zone de gamma concentré.",
        "positive": "Le gamma augmente si le spot monte ; la fréquence de hedge peut accélérer sur la hausse.",
        "negative": "Le gamma diminue si le spot monte, ou augmente sur la baisse ; le risque de convexité est asymétrique.",
        "hedge": "Déplacer/répartir les strikes, réduire la concentration très court terme et tester le hedge sur une grille de spot plutôt qu'au seul spot courant.",
        "structures": "Butterflies, ratios et books concentrés autour d'un strike peuvent produire un speed élevé et changer de signe rapidement.",
        "caveat": "Dérivée d'ordre trois, donc bruitée et très modèle-dépendante. Toujours la lire avec la courbe gamma complète.",
    },
    "Color": {
        "key": "color_1d",
        "formula": "Color ≈ Gamma(t + 1 jour) - Gamma(t)",
        "unit": "gamma par jour calendaire",
        "definition": "Évolution temporelle du gamma : indique si le risque de re-hedge augmentera ou diminuera sans mouvement du spot.",
        "variants": "Comme charm, le signe varie selon la convention temps écoulé/temps restant. Ici, positif = gamma plus élevé demain.",
        "drivers": "DTE, distance au strike, IV et calendrier. Le color devient critique autour de l'ATM à l'approche de l'expiration.",
        "positive": "Le gamma augmentera avec le passage du temps ; préparer davantage de re-hedging et de liquidité.",
        "negative": "Le gamma diminuera avec le passage du temps ; la convexité se dissipe, mais le book peut rester exposé au gap.",
        "hedge": "Roller ou redistribuer l'échéance, limiter les concentrations 0DTE/hebdomadaires et dimensionner les besoins de re-hedge futurs.",
        "structures": "Positions ATM courtes maturités, calendars et butterflies ont souvent un color matériel.",
        "caveat": "L'hypothèse de spot/IV constants est forte. Un déplacement de skew peut dominer le color calculé.",
    },
    "Zomma": {
        "key": "zomma_1vol",
        "formula": "Zomma = ∂Gamma/∂σ",
        "unit": "gamma pour +1 point de volatilité",
        "definition": "Variation du gamma sous choc d'IV ; relie risque de convexité spot et régime de volatilité.",
        "variants": "Zomma BSM applique un choc parallèle. Une zomma de surface dépend du strike, de la maturité et de la dynamique du smile.",
        "drivers": "Moneyness, DTE, niveau d'IV et forme du skew. Peut changer de signe selon la zone de la surface.",
        "positive": "Le gamma augmente lorsque l'IV monte ; le besoin de re-hedging peut croître en même temps que le marché devient plus volatil.",
        "negative": "Le gamma diminue lorsque l'IV monte ; la protection convexe peut être moins réactive que prévu sous stress.",
        "hedge": "Stress conjoint spot-IV, options de strikes/maturités différents et limites sur gamma conditionnel, pas seulement gamma courant.",
        "structures": "Books d'ailes, calendars et ratios peuvent avoir une zomma importante malgré un gamma courant modeste.",
        "caveat": "Le choc parallèle ne représente pas un vrai stress de surface. Toujours compléter par skew, term structure et scénarios sticky-delta/strike.",
    },
}


def _greek_key(greek: str) -> str:
    if greek not in GREEK_ANALYTICS:
        raise ValueError(f"Greek inconnu: {greek}")
    return GREEK_ANALYTICS[greek]["key"]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else float(default)
    except Exception:
        return float(default)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1_d2(spot: float, strike: float, t: float, rate: float, dividend: float, iv: float) -> Tuple[float, float]:
    root_t = math.sqrt(max(t, EPS))
    d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * iv * iv) * t) / max(iv * root_t, EPS)
    return d1, d1 - iv * root_t


def black_scholes_price(
    spot: float,
    strike: float,
    t: float,
    rate: float,
    dividend: float,
    iv: float,
    option_type: str,
) -> float:
    """European Black-Scholes-Merton value per share."""
    spot, strike, t, iv = map(_finite, (spot, strike, t, iv))
    if spot <= 0 or strike <= 0:
        return 0.0
    if t <= EPS or iv <= EPS:
        return max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    d1, d2 = _d1_d2(spot, strike, t, rate, dividend, iv)
    df_r, df_q = math.exp(-rate * t), math.exp(-dividend * t)
    if option_type == "call":
        return spot * df_q * _norm_cdf(d1) - strike * df_r * _norm_cdf(d2)
    return strike * df_r * _norm_cdf(-d2) - spot * df_q * _norm_cdf(-d1)


def black_scholes_greeks(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    option_type: str,
    rate: float = 0.045,
    dividend: float = 0.0,
) -> Dict[str, float]:
    """Greeks with explicit practical scaling and stable finite-difference cross-checks."""
    t = max(_finite(dte) / CALENDAR_DAYS, 0.5 / CALENDAR_DAYS)
    spot, strike, iv = _finite(spot), _finite(strike), max(_finite(iv), 0.0001)
    if spot <= 0 or strike <= 0:
        return {k: 0.0 for k in ("price", "delta", "gamma", "vega_1vol", "theta_1d", "rho_100bp", "vanna_1vol", "vomma_1vol2", "charm_1d", "speed", "color_1d", "zomma_1vol", "prob_itm")}

    d1, d2 = _d1_d2(spot, strike, t, rate, dividend, iv)
    pdf, df_r, df_q = _norm_pdf(d1), math.exp(-rate * t), math.exp(-dividend * t)
    root_t = math.sqrt(t)
    gamma = df_q * pdf / max(spot * iv * root_t, EPS)
    vega_raw = spot * df_q * pdf * root_t
    if option_type == "call":
        delta = df_q * _norm_cdf(d1)
        theta_year = -(spot * df_q * pdf * iv) / (2.0 * root_t) - rate * strike * df_r * _norm_cdf(d2) + dividend * spot * df_q * _norm_cdf(d1)
        rho_raw = strike * t * df_r * _norm_cdf(d2)
        prob_itm = _norm_cdf(d2)
    else:
        delta = -df_q * _norm_cdf(-d1)
        theta_year = -(spot * df_q * pdf * iv) / (2.0 * root_t) + rate * strike * df_r * _norm_cdf(-d2) - dividend * spot * df_q * _norm_cdf(-d1)
        rho_raw = -strike * t * df_r * _norm_cdf(-d2)
        prob_itm = _norm_cdf(-d2)

    vanna_1vol = -df_q * pdf * d2 / max(iv, EPS) * 0.01
    vomma_1vol2 = vega_raw * d1 * d2 / max(iv, EPS) * 0.0001
    speed = -gamma / max(spot, EPS) * (d1 / max(iv * root_t, EPS) + 1.0)
    zomma_1vol = gamma * ((d1 * d2 - 1.0) / max(iv, EPS)) * 0.01

    next_t = max(t - 1.0 / CALENDAR_DAYS, 0.5 / CALENDAR_DAYS)
    nd1, _ = _d1_d2(spot, strike, next_t, rate, dividend, iv)
    next_delta = math.exp(-dividend * next_t) * (_norm_cdf(nd1) if option_type == "call" else -_norm_cdf(-nd1))
    next_gamma = math.exp(-dividend * next_t) * _norm_pdf(nd1) / max(spot * iv * math.sqrt(next_t), EPS)

    return {
        "price": black_scholes_price(spot, strike, t, rate, dividend, iv, option_type),
        "delta": delta,
        "gamma": gamma,
        "vega_1vol": vega_raw / 100.0,
        "theta_1d": theta_year / CALENDAR_DAYS,
        "rho_100bp": rho_raw / 100.0,
        "vanna_1vol": vanna_1vol,
        "vomma_1vol2": vomma_1vol2,
        "charm_1d": next_delta - delta,
        "speed": speed,
        "color_1d": next_gamma - gamma,
        "zomma_1vol": zomma_1vol,
        "prob_itm": prob_itm,
    }


def option_intrinsic(spot: np.ndarray | float, strike: float, option_type: str) -> np.ndarray:
    values = np.asarray(spot, dtype=float)
    return np.maximum(values - strike, 0.0) if option_type == "call" else np.maximum(strike - values, 0.0)


def strategy_pnl_at_expiry(legs: Sequence[StrategyLeg], terminal_spots: np.ndarray | Sequence[float]) -> np.ndarray:
    spots = np.asarray(terminal_spots, dtype=float)
    pnl = np.zeros_like(spots)
    for leg in legs:
        if leg.instrument == "stock":
            pnl += leg.signed_units * (spots - leg.premium)
        else:
            pnl += leg.signed_units * (option_intrinsic(spots, leg.strike, leg.instrument) - leg.premium)
    return pnl


def strategy_mark_pnl(
    legs: Sequence[StrategyLeg],
    spots: np.ndarray | Sequence[float],
    days_elapsed: int,
    iv_shift_points: float = 0.0,
    rate: float = 0.045,
    dividend: float = 0.0,
) -> np.ndarray:
    spot_values = np.asarray(spots, dtype=float)
    pnl = np.zeros_like(spot_values)
    for leg in legs:
        if leg.instrument == "stock":
            pnl += leg.signed_units * (spot_values - leg.premium)
            continue
        remaining = max(leg.dte - int(days_elapsed), 0)
        scenario_iv = max(leg.iv + iv_shift_points / 100.0, 0.0001)
        if remaining <= 0:
            mark = option_intrinsic(spot_values, leg.strike, leg.instrument)
        else:
            mark = np.array([
                black_scholes_price(float(s), leg.strike, remaining / CALENDAR_DAYS, rate, dividend, scenario_iv, leg.instrument)
                for s in spot_values
            ])
        pnl += leg.signed_units * (mark - leg.premium)
    return pnl


def aggregate_strategy_greeks(
    legs: Sequence[StrategyLeg],
    spot: float,
    days_elapsed: int = 0,
    iv_shift_points: float = 0.0,
    rate: float = 0.045,
    dividend: float = 0.0,
) -> Dict[str, float]:
    totals = {k: 0.0 for k in ("delta", "dollar_delta", "gamma", "dollar_gamma_1pct", "vega_1vol", "theta_1d", "rho_100bp", "vanna_1vol", "vomma_1vol2", "charm_1d", "speed", "color_1d", "zomma_1vol")}
    for leg in legs:
        if leg.instrument == "stock":
            totals["delta"] += leg.signed_units
            totals["dollar_delta"] += leg.signed_units * spot
            continue
        greeks = black_scholes_greeks(
            spot,
            leg.strike,
            max(leg.dte - days_elapsed, 0),
            max(leg.iv + iv_shift_points / 100.0, 0.0001),
            leg.instrument,
            rate,
            dividend,
        )
        units = leg.signed_units
        totals["delta"] += units * greeks["delta"]
        totals["dollar_delta"] += units * greeks["delta"] * spot
        totals["gamma"] += units * greeks["gamma"]
        totals["dollar_gamma_1pct"] += 0.5 * units * greeks["gamma"] * (spot * 0.01) ** 2
        for key in ("vega_1vol", "theta_1d", "rho_100bp", "vanna_1vol", "vomma_1vol2", "charm_1d", "speed", "color_1d", "zomma_1vol"):
            totals[key] += units * greeks[key]
    return totals


def build_greek_profile(
    legs: Sequence[StrategyLeg],
    spot: float,
    greek: str,
    spot_multipliers: Sequence[float],
    iv_shifts: Sequence[float],
    days_elapsed: Sequence[int],
    rate: float = 0.045,
    dividend: float = 0.0,
) -> pd.DataFrame:
    """Cartesian Greek scenario cube for spot, IV and elapsed time."""
    key = _greek_key(greek)
    rows: List[Dict[str, float | int | str]] = []
    for day in days_elapsed:
        for iv_shift in iv_shifts:
            for multiplier in spot_multipliers:
                scenario_spot = max(float(spot) * float(multiplier), EPS)
                totals = aggregate_strategy_greeks(
                    legs,
                    scenario_spot,
                    max(int(day), 0),
                    float(iv_shift),
                    rate,
                    dividend,
                )
                rows.append({
                    "Greek": greek,
                    "Spot": scenario_spot,
                    "Spot shock": float(multiplier) - 1.0,
                    "IV shift": float(iv_shift),
                    "Days elapsed": max(int(day), 0),
                    "Exposure": _finite(totals.get(key)),
                })
    return pd.DataFrame(rows)


def greek_leg_contributions(
    legs: Sequence[StrategyLeg],
    spot: float,
    greek: str,
    rate: float = 0.045,
    dividend: float = 0.0,
) -> pd.DataFrame:
    """Per-leg contribution in the exact display convention of a selected Greek."""
    key = _greek_key(greek)
    rows: List[Dict[str, Any]] = []
    for index, leg in enumerate(legs, start=1):
        if leg.instrument == "stock":
            contribution = leg.signed_units if key == "delta" else 0.0
        else:
            raw = black_scholes_greeks(
                spot,
                leg.strike,
                leg.dte,
                leg.iv,
                leg.instrument,
                rate,
                dividend,
            )
            if key == "dollar_gamma_1pct":
                contribution = 0.5 * leg.signed_units * raw["gamma"] * (spot * 0.01) ** 2
            else:
                contribution = leg.signed_units * raw[key]
        rows.append({
            "Jambe": leg.label or f"{index}. {leg.instrument.title()} {leg.strike:,.2f}",
            "Type": leg.instrument.title(),
            "Sens": "Long" if leg.side > 0 else "Short",
            "Quantité": leg.quantity,
            "Strike": leg.strike,
            "Contribution": _finite(contribution),
        })
    return pd.DataFrame(rows)


def build_cross_greek_shocks(
    legs: Sequence[StrategyLeg],
    spot: float,
    rate: float = 0.045,
    dividend: float = 0.0,
) -> pd.DataFrame:
    """Canonical shocks showing how every Greek moves when another risk factor changes."""
    base = aggregate_strategy_greeks(legs, spot, 0, 0.0, rate, dividend)
    scenarios = (
        ("Spot -1%", spot * 0.99, 0, 0.0, rate),
        ("Spot +1%", spot * 1.01, 0, 0.0, rate),
        ("IV -5 pts", spot, 0, -5.0, rate),
        ("IV +5 pts", spot, 0, 5.0, rate),
        ("Temps +1j", spot, 1, 0.0, rate),
        ("Taux +100bp", spot, 0, 0.0, rate + 0.01),
    )
    rows: List[Dict[str, Any]] = []
    for scenario, scenario_spot, day, iv_shift, scenario_rate in scenarios:
        shocked = aggregate_strategy_greeks(
            legs,
            scenario_spot,
            day,
            iv_shift,
            scenario_rate,
            dividend,
        )
        for greek, spec in GREEK_ANALYTICS.items():
            key = spec["key"]
            rows.append({
                "Scénario": scenario,
                "Greek": greek,
                "Base": _finite(base.get(key)),
                "Après choc": _finite(shocked.get(key)),
                "Variation": _finite(shocked.get(key)) - _finite(base.get(key)),
                "Unité": spec["unit"],
            })
    return pd.DataFrame(rows)


def _break_evens(spots: np.ndarray, pnl: np.ndarray) -> Tuple[float, ...]:
    roots: List[float] = []
    for idx in range(len(spots) - 1):
        y0, y1 = pnl[idx], pnl[idx + 1]
        if abs(y0) < 1e-9:
            roots.append(float(spots[idx]))
        elif y0 * y1 < 0:
            roots.append(float(spots[idx] - y0 * (spots[idx + 1] - spots[idx]) / (y1 - y0)))
    if abs(pnl[-1]) < 1e-9:
        roots.append(float(spots[-1]))
    deduped: List[float] = []
    for root in roots:
        if not deduped or abs(root - deduped[-1]) > 1e-4:
            deduped.append(root)
    return tuple(deduped)


def _profit_probability(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    sigma: float,
    drift: float,
) -> Optional[float]:
    if spot <= 0 or dte <= 0 or sigma <= 0:
        return None
    nodes, weights = np.polynomial.hermite.hermgauss(64)
    t = dte / CALENDAR_DAYS
    terminal = spot * np.exp((drift - 0.5 * sigma * sigma) * t + sigma * math.sqrt(2.0 * t) * nodes)
    pnl = strategy_pnl_at_expiry(legs, terminal)
    return float(np.sum(weights * (pnl > 0).astype(float)) / math.sqrt(math.pi))


def _expected_pnl(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    sigma: float,
    drift: float,
) -> Optional[float]:
    if spot <= 0 or dte <= 0 or sigma <= 0:
        return None
    nodes, weights = np.polynomial.hermite.hermgauss(64)
    t = dte / CALENDAR_DAYS
    terminal = spot * np.exp((drift - 0.5 * sigma * sigma) * t + sigma * math.sqrt(2.0 * t) * nodes)
    pnl = strategy_pnl_at_expiry(legs, terminal)
    return float(np.sum(weights * pnl) / math.sqrt(math.pi))


def summarize_strategy(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    sigma: float,
    drift: float = 0.0,
) -> StrategySummary:
    strikes = [leg.strike for leg in legs if leg.instrument != "stock" and leg.strike > 0]
    high_anchor = max(strikes + [spot])
    grid = np.linspace(max(0.01, min(strikes + [spot]) * 0.05), max(spot * 3.0, high_anchor * 2.25), 5001)
    pnl = strategy_pnl_at_expiry(legs, grid)
    break_evens = _break_evens(grid, pnl)
    net_debit = float(sum(leg.signed_units * leg.premium for leg in legs))

    right_slope = sum(leg.signed_units for leg in legs if leg.instrument == "stock")
    right_slope += sum(leg.signed_units for leg in legs if leg.instrument == "call")
    if right_slope > EPS:
        max_profit, right_tail = math.inf, "Profit non borné à la hausse"
    else:
        max_profit = float(np.max(pnl))
        right_tail = "Payoff borné"
    max_loss = math.inf if right_slope < -EPS else max(0.0, float(-np.min(pnl)))
    capital_at_risk = max_loss if math.isfinite(max_loss) else max(abs(net_debit), abs(float(np.min(pnl))))
    reward_to_risk = None
    if math.isfinite(max_profit) and math.isfinite(max_loss) and max_loss > EPS:
        reward_to_risk = max_profit / max_loss
    return StrategySummary(
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=max_loss,
        break_evens=break_evens,
        probability_of_profit=_profit_probability(legs, spot, dte, sigma, drift),
        expected_pnl=_expected_pnl(legs, spot, dte, sigma, drift),
        reward_to_risk=reward_to_risk,
        capital_at_risk=capital_at_risk,
        right_tail=right_tail,
    )


def pnl_attribution(
    legs: Sequence[StrategyLeg],
    spot: float,
    spot_shock_pct: float,
    iv_shift_points: float,
    days_elapsed: int,
    rate: float = 0.045,
    dividend: float = 0.0,
) -> Dict[str, float]:
    base = strategy_mark_pnl(legs, [spot], 0, 0.0, rate, dividend)[0]
    shocked_spot = spot * (1.0 + spot_shock_pct)
    exact = strategy_mark_pnl(legs, [shocked_spot], days_elapsed, iv_shift_points, rate, dividend)[0] - base
    greeks = aggregate_strategy_greeks(legs, spot, 0, 0.0, rate, dividend)
    ds = shocked_spot - spot
    components = {
        "Delta": greeks["delta"] * ds,
        "Gamma": 0.5 * greeks["gamma"] * ds * ds,
        "Vega": greeks["vega_1vol"] * iv_shift_points,
        "Theta": greeks["theta_1d"] * days_elapsed,
        "Vanna": greeks["vanna_1vol"] * iv_shift_points * ds,
        "Vomma": 0.5 * greeks["vomma_1vol2"] * iv_shift_points * iv_shift_points,
    }
    components["Résiduel modèle"] = exact - sum(components.values())
    components["P&L exact"] = exact
    return components


def scenario_matrix(
    legs: Sequence[StrategyLeg],
    spot: float,
    days_elapsed: int,
    spot_shocks: Sequence[float],
    iv_shifts: Sequence[float],
    rate: float = 0.045,
    dividend: float = 0.0,
) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []
    for iv_shift in iv_shifts:
        values = strategy_mark_pnl(
            legs,
            [spot * (1.0 + shock) for shock in spot_shocks],
            days_elapsed,
            iv_shift,
            rate,
            dividend,
        )
        for shock, value in zip(spot_shocks, values):
            rows.append({"Spot shock": float(shock), "IV shift": float(iv_shift), "P&L": float(value)})
    return pd.DataFrame(rows)


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame is None or frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _available_strikes(calls: pd.DataFrame, puts: pd.DataFrame) -> List[float]:
    values: List[float] = []
    for frame in (calls, puts):
        values.extend(_numeric_series(frame, "strike").dropna().astype(float).tolist())
    return sorted(set(x for x in values if x > 0))


def _nearest_strike(strikes: Sequence[float], target: float) -> float:
    if not strikes:
        return float(target)
    return float(min(strikes, key=lambda value: abs(value - target)))


def _chain_quote(frame: pd.DataFrame, strike: float) -> Mapping[str, float]:
    if frame is None or frame.empty or "strike" not in frame.columns:
        return {}
    work = frame.copy()
    work["_distance"] = (_numeric_series(work, "strike") - strike).abs()
    if work["_distance"].dropna().empty:
        return {}
    row = work.loc[work["_distance"].idxmin()]
    return {name: _finite(row.get(name)) for name in ("strike", "mid", "bid", "ask", "iv", "dte")}


def _make_option_leg(
    option_type: str,
    side: int,
    quantity: int,
    strike: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    price_mode: str,
    fallback_iv: float,
    fallback_dte: int,
    label: str,
) -> StrategyLeg:
    quote = _chain_quote(calls if option_type == "call" else puts, strike)
    bid, ask, mid = (_finite(quote.get(k)) for k in ("bid", "ask", "mid"))
    if mid <= 0 and bid > 0 and ask > 0:
        mid = 0.5 * (bid + ask)
    if price_mode.startswith("Exécutable"):
        premium = ask if side > 0 and ask > 0 else bid if side < 0 and bid > 0 else mid
    else:
        premium = mid
    return StrategyLeg(
        instrument=option_type,
        side=1 if side >= 0 else -1,
        quantity=max(int(quantity), 1),
        strike=_finite(quote.get("strike"), strike),
        premium=max(premium, 0.0),
        iv=max(_finite(quote.get("iv"), fallback_iv), 0.0001),
        dte=max(int(_finite(quote.get("dte"), fallback_dte)), 0),
        bid=max(bid, 0.0),
        ask=max(ask, 0.0),
        label=label,
    )


def build_template_legs(
    template: str,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    dte: int,
    atm_iv: float,
    center_strike: Optional[float] = None,
    width_steps: int = 2,
    wing_steps: int = 2,
    contracts: int = 1,
    price_mode: str = "Exécutable (ask/bid)",
) -> List[StrategyLeg]:
    strikes = _available_strikes(calls, puts)
    if not strikes:
        return []
    diffs = np.diff(np.array(strikes))
    spacing = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else max(spot * 0.025, 1.0)
    center = _nearest_strike(strikes, center_strike or spot)
    width = max(int(width_steps), 1) * spacing
    wing = max(int(wing_steps), 1) * spacing
    low = _nearest_strike(strikes, center - width)
    high = _nearest_strike(strikes, center + width)
    far_low = _nearest_strike(strikes, low - wing)
    far_high = _nearest_strike(strikes, high + wing)
    broken_high = _nearest_strike(strikes, high + wing)

    def opt(kind: str, side: int, qty: int, strike: float, label: str) -> StrategyLeg:
        return _make_option_leg(kind, side, qty * contracts, strike, calls, puts, price_mode, atm_iv, dte, label)

    stock = StrategyLeg("stock", 1, 100 * contracts, premium=spot, dte=dte, label="Sous-jacent")
    recipes: Dict[str, List[StrategyLeg]] = {
        "Long Call": [opt("call", 1, 1, center, "Call acheté")],
        "Long Put": [opt("put", 1, 1, center, "Put acheté")],
        "Bull Call Spread": [opt("call", 1, 1, center, "Call long"), opt("call", -1, 1, high, "Call court")],
        "Bear Put Spread": [opt("put", 1, 1, center, "Put long"), opt("put", -1, 1, low, "Put court")],
        "Covered Call": [stock, opt("call", -1, 1, high, "Call couvert")],
        "Protective Put": [stock, opt("put", 1, 1, low, "Put de protection")],
        "Collar": [stock, opt("put", 1, 1, low, "Put plancher"), opt("call", -1, 1, high, "Call plafond")],
        "Long Straddle": [opt("call", 1, 1, center, "Call ATM"), opt("put", 1, 1, center, "Put ATM")],
        "Long Strangle": [opt("put", 1, 1, low, "Put OTM"), opt("call", 1, 1, high, "Call OTM")],
        "Short Strangle": [opt("put", -1, 1, low, "Put court"), opt("call", -1, 1, high, "Call court")],
        "Call Butterfly": [opt("call", 1, 1, low, "Aile basse"), opt("call", -1, 2, center, "Corps x2"), opt("call", 1, 1, high, "Aile haute")],
        "Broken-Wing Butterfly": [opt("call", 1, 1, low, "Aile basse"), opt("call", -1, 2, center, "Corps x2"), opt("call", 1, 1, broken_high, "Aile haute élargie")],
        "Iron Butterfly": [opt("put", 1, 1, low, "Put aile"), opt("put", -1, 1, center, "Put court"), opt("call", -1, 1, center, "Call court"), opt("call", 1, 1, high, "Call aile")],
        "Iron Condor": [opt("put", 1, 1, far_low, "Put aile"), opt("put", -1, 1, low, "Put court"), opt("call", -1, 1, high, "Call court"), opt("call", 1, 1, far_high, "Call aile")],
        "Risk Reversal": [opt("put", -1, 1, low, "Put de financement"), opt("call", 1, 1, high, "Call directionnel")],
    }
    return recipes.get(template, recipes["Bull Call Spread"])


def legs_to_frame(legs: Sequence[StrategyLeg]) -> pd.DataFrame:
    rows = []
    for leg in legs:
        rows.append({
            "Label": leg.label,
            "Side": "Long" if leg.side > 0 else "Short",
            "Type": {"call": "Call", "put": "Put", "stock": "Action"}.get(leg.instrument, leg.instrument),
            "Quantité": leg.quantity,
            "Strike": leg.strike if leg.instrument != "stock" else np.nan,
            "Prime": leg.premium,
            "IV %": leg.iv * 100.0,
            "DTE": leg.dte,
            "Bid": leg.bid,
            "Ask": leg.ask,
        })
    return pd.DataFrame(rows)


def frame_to_legs(frame: pd.DataFrame, default_dte: int, default_iv: float) -> List[StrategyLeg]:
    legs: List[StrategyLeg] = []
    for _, row in frame.iterrows():
        kind = str(row.get("Type", "Call")).strip().lower()
        instrument = "stock" if kind in {"action", "stock", "sous-jacent"} else "put" if kind.startswith("p") else "call"
        side = -1 if str(row.get("Side", "Long")).lower().startswith("s") else 1
        quantity = max(int(_finite(row.get("Quantité"), 1)), 1)
        legs.append(StrategyLeg(
            instrument=instrument,
            side=side,
            quantity=quantity,
            strike=max(_finite(row.get("Strike")), 0.0),
            premium=max(_finite(row.get("Prime")), 0.0),
            iv=max(_finite(row.get("IV %"), default_iv * 100.0) / 100.0, 0.0001),
            dte=max(int(_finite(row.get("DTE"), default_dte)), 0),
            bid=max(_finite(row.get("Bid")), 0.0),
            ask=max(_finite(row.get("Ask")), 0.0),
            label=str(row.get("Label", "Jambe")),
        ))
    return legs


def quote_quality(legs: Sequence[StrategyLeg]) -> Dict[str, Any]:
    option_legs = [leg for leg in legs if leg.instrument != "stock"]
    if not option_legs:
        return {"score": 100.0, "spread_cost": 0.0, "missing": 0, "state": "Sous-jacent uniquement"}
    spread_cost = sum(max(leg.ask - leg.bid, 0.0) * leg.quantity * CONTRACT_MULTIPLIER for leg in option_legs)
    gross_mid = sum(max((leg.ask + leg.bid) * 0.5, leg.premium, 0.01) * leg.quantity * CONTRACT_MULTIPLIER for leg in option_legs)
    missing = sum(1 for leg in option_legs if leg.bid <= 0 or leg.ask <= 0)
    spread_ratio = spread_cost / max(gross_mid, EPS)
    score = max(0.0, min(100.0, 100.0 - spread_ratio * 140.0 - missing * 18.0))
    state = "Exécutable" if score >= 75 else "À travailler en limite" if score >= 50 else "Quotes fragiles"
    return {"score": score, "spread_cost": spread_cost, "spread_ratio": spread_ratio, "missing": missing, "state": state}


def rank_strategy_templates(
    directional_view: str,
    volatility_view: str,
    iv_premium: Optional[float],
    dte: int,
    liquidity_score: float,
) -> pd.DataFrame:
    direction_target = {"Baissier": -1.0, "Neutre / range": 0.0, "Haussier": 1.0}.get(directional_view, 0.0)
    vol_target = {"Expansion": 1.0, "Stable": 0.0, "Compression": -1.0}.get(volatility_view, 0.0)
    premium = _finite(iv_premium)
    rows = []
    for name, profile in STRATEGY_PROFILES.items():
        direction_fit = 100.0 - abs(profile["direction"] - direction_target) * 50.0
        vol_fit = 100.0 - abs(profile["vol"] - vol_target) * 50.0
        value_fit = 50.0
        if premium > 0.15:
            value_fit = 50.0 + max(-40.0, min(40.0, -profile["vol"] * premium * 120.0))
        elif premium < -0.10:
            value_fit = 50.0 + max(-40.0, min(40.0, profile["vol"] * abs(premium) * 120.0))
        dte_fit = 82.0 if dte >= 7 else 55.0 if profile["vol"] >= 0 else 45.0
        complexity_penalty = max(profile["complexity"] - 2, 0) * (100.0 - liquidity_score) * 0.08
        score = max(0.0, min(100.0, 0.42 * direction_fit + 0.31 * vol_fit + 0.17 * value_fit + 0.10 * dte_fit - complexity_penalty))
        rows.append({"Stratégie": name, "Fit": score, "Thèse": profile["thesis"], "Jambes": profile["complexity"], "Régime vol": "Long vol" if profile["vol"] > 0.3 else "Short vol" if profile["vol"] < -0.3 else "Vol modérée"})
    return pd.DataFrame(rows).sort_values("Fit", ascending=False).reset_index(drop=True)


def _money(value: float) -> str:
    if math.isinf(value):
        return "Non borné"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.1f}K"
    return f"{sign}${value:,.0f}"


def _pct(value: Optional[float]) -> str:
    return "N/A" if value is None or not math.isfinite(value) else f"{value:.1%}"


def _strategy_chart(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    expected_move: float,
    iv_shift: float,
    horizon: int,
    rate: float,
    dividend: float,
) -> go.Figure:
    strikes = [leg.strike for leg in legs if leg.instrument != "stock"]
    radius = max(expected_move * 1.8, spot * 0.22, (max(strikes) - min(strikes)) * 1.8 if len(strikes) > 1 else 0.0)
    grid = np.linspace(max(0.01, spot - radius), spot + radius, 601)
    expiry = strategy_pnl_at_expiry(legs, grid)
    scenario = strategy_mark_pnl(legs, grid, horizon, iv_shift, rate, dividend)
    halfway = strategy_mark_pnl(legs, grid, min(max(dte // 2, 0), dte), 0.0, rate, dividend)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=grid, y=expiry, mode="lines", name="Expiration", line=dict(color="#22d3ee", width=3)))
    fig.add_trace(go.Scatter(x=grid, y=scenario, mode="lines", name=f"Scénario J+{horizon} / IV {iv_shift:+.0f} pts", line=dict(color="#a78bfa", width=2)))
    if 0 < dte // 2 < dte:
        fig.add_trace(go.Scatter(x=grid, y=halfway, mode="lines", name=f"Mi-vie J+{dte // 2}", line=dict(color="#64748b", dash="dot")))
    fig.add_hline(y=0, line_color="#94a3b8", line_width=1)
    fig.add_vline(
        x=spot,
        line_color="#f8fafc",
        line_dash="dash",
        annotation_text="Spot",
        annotation_position="bottom right",
    )
    if expected_move > 0:
        fig.add_vrect(
            x0=max(0.0, spot - expected_move),
            x1=spot + expected_move,
            fillcolor="#0ea5e9",
            opacity=0.08,
            line_width=0,
            annotation_text="Expected move ±1σ",
            annotation_position="top left",
        )
    fig.update_layout(
        height=520,
        margin=dict(l=15, r=15, t=45, b=15),
        paper_bgcolor="#07111c",
        plot_bgcolor="#07111c",
        font=dict(color="#dbeafe"),
        title="Profil P&L multi-horizons",
        xaxis_title="Prix du sous-jacent",
        yaxis_title="P&L ($)",
        legend=dict(orientation="h", y=1.08),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,.12)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,.12)", zeroline=False)
    return fig


def _render_metric_strip(items: Sequence[Tuple[str, str, str]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, note) in zip(columns, items):
        with column:
            st.metric(label, value)
            st.caption(note)


def _render_payoff_and_scenarios(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    atm_iv: float,
    metrics: Mapping[str, Any],
    horizon: int,
    spot_shock: float,
    iv_shift: float,
    rate: float,
    dividend: float,
    drift: float,
) -> None:
    summary = summarize_strategy(legs, spot, dte, atm_iv, drift)
    quality = quote_quality(legs)
    expected_move = _finite(metrics.get("expected_move_price"), spot * atm_iv * math.sqrt(max(dte, 1) / CALENDAR_DAYS))
    be_text = " · ".join(f"{value:,.2f}" for value in summary.break_evens) or "Aucun dans la grille"
    _render_metric_strip([
        ("Débit / crédit", _money(summary.net_debit), "Débit + · crédit -"),
        ("Profit max", _money(summary.max_profit), summary.right_tail),
        ("Perte max", _money(summary.max_loss), "Hors marge broker"),
        ("Break-even", be_text, f"{len(summary.break_evens)} niveau(x)"),
        ("Probabilité profit", _pct(summary.probability_of_profit), "Lognormale, hypothèse utilisateur"),
        ("Quote quality", f"{quality['score']:.0f}/100", str(quality["state"])),
    ])
    st.plotly_chart(_strategy_chart(legs, spot, dte, expected_move, iv_shift, horizon, rate, dividend), width="stretch", key="strategy_lab_payoff")

    attr = pnl_attribution(legs, spot, spot_shock, iv_shift, horizon, rate, dividend)
    st.markdown("#### Attribution locale du scénario")
    left, right = st.columns([1.0, 1.15])
    with left:
        attr_rows = [{"Facteur": key, "P&L": value} for key, value in attr.items() if key != "P&L exact"]
        attr_fig = go.Figure(go.Bar(
            x=[row["P&L"] for row in attr_rows],
            y=[row["Facteur"] for row in attr_rows],
            orientation="h",
            marker_color=["#22c55e" if row["P&L"] >= 0 else "#ef4444" for row in attr_rows],
        ))
        attr_fig.update_layout(height=380, margin=dict(l=15, r=15, t=25, b=15), paper_bgcolor="#07111c", plot_bgcolor="#07111c", font=dict(color="#dbeafe"), xaxis_title="Contribution P&L ($)")
        st.plotly_chart(attr_fig, width="stretch", key="strategy_lab_attribution")
    with right:
        spot_shocks = np.array([-0.20, -0.12, -0.08, -0.04, 0.0, 0.04, 0.08, 0.12, 0.20])
        iv_shifts = np.array([-20.0, -10.0, -5.0, 0.0, 5.0, 10.0, 20.0])
        matrix = scenario_matrix(legs, spot, horizon, spot_shocks, iv_shifts, rate, dividend)
        pivot = matrix.pivot(index="IV shift", columns="Spot shock", values="P&L").sort_index(ascending=False)
        heat = go.Figure(go.Heatmap(
            z=pivot.values,
            x=[f"{x:+.0%}" for x in pivot.columns],
            y=[f"{y:+.0f} vol" for y in pivot.index],
            colorscale=[[0, "#7f1d1d"], [0.5, "#111827"], [1, "#14532d"]],
            zmid=0,
            colorbar=dict(title="P&L"),
            hovertemplate="Spot %{x}<br>IV %{y}<br>P&L $%{z:,.0f}<extra></extra>",
        ))
        heat.update_layout(height=380, margin=dict(l=15, r=15, t=25, b=15), paper_bgcolor="#07111c", font=dict(color="#dbeafe"), xaxis_title="Choc spot", yaxis_title="Choc IV")
        st.plotly_chart(heat, width="stretch", key="strategy_lab_heatmap")
    st.caption(f"P&L exact du scénario choisi : {_money(attr['P&L exact'])}. L'attribution Greek est une approximation locale ; le résiduel mesure non-linéarités et interaction de surface non captées.")


def _format_greek_exposure(value: float) -> str:
    value = _finite(value)
    if abs(value) >= 1.0:
        return f"{value:+,.2f}"
    if abs(value) >= 0.001:
        return f"{value:+,.5f}"
    return f"{value:+.3e}"


def _render_delta_lenses(
    legs: Sequence[StrategyLeg],
    spot: float,
    totals: Mapping[str, float],
    rate: float,
    dividend: float,
) -> None:
    st.markdown("##### Delta — trois définitions opérationnelles")
    delta_cols = st.columns(3)
    with delta_cols[0]:
        st.info(
            f"**1 · Sensibilité de prix**\n\n∂V/∂S = **{totals['delta']:+,.1f} USD** de P&L local "
            "pour +1 USD de spot."
        )
    with delta_cols[1]:
        st.info(
            f"**2 · Ratio de couverture**\n\nHedge instantané = **{-totals['delta']:+,.1f} actions** "
            "pour ramener le delta vers zéro."
        )
    with delta_cols[2]:
        st.info(
            f"**3 · Cash / dollar delta**\n\nExposition directionnelle = **{_money(totals['dollar_delta'])}** "
            "pour comparer le risque notionnel."
        )
    option_legs = [leg for leg in legs if leg.instrument != "stock"]
    probabilities = [
        black_scholes_greeks(spot, leg.strike, leg.dte, leg.iv, leg.instrument, rate, dividend)["prob_itm"]
        for leg in option_legs
    ]
    mean_prob = float(np.mean(probabilities)) if probabilities else 0.0
    st.warning(
        f"**Probabilité : ne pas créer une quatrième définition.** N(d₂) moyen descriptif des jambes = "
        f"**{mean_prob:.1%}** ; le delta utilise N(d₁). Ni l'un ni l'autre n'est la probabilité de profit de la stratégie multi-jambes."
    )


def _render_greek_overview(
    legs: Sequence[StrategyLeg],
    spot: float,
    totals: Mapping[str, float],
    rate: float,
    dividend: float,
) -> None:
    rows = []
    for greek, spec in GREEK_ANALYTICS.items():
        value = _finite(totals.get(spec["key"]))
        direction = "Positif" if value > EPS else "Négatif" if value < -EPS else "Neutre"
        reading = spec["positive"] if value > EPS else spec["negative"] if value < -EPS else "Exposition locale proche de zéro ; vérifier sa stabilité sous scénario."
        rows.append({
            "Greek": greek,
            "Exposition": _format_greek_exposure(value),
            "Unité": spec["unit"],
            "Signe": direction,
            "Lecture décisionnelle": reading,
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    _render_delta_lenses(legs, spot, totals, rate, dividend)
    st.caption("Les valeurs de Greeks n'ont pas la même unité et ne doivent jamais être additionnées ou comparées sur une barre de score commune.")


def _render_selected_greek_analysis(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    totals: Mapping[str, float],
    rate: float,
    dividend: float,
) -> None:
    selected = st.selectbox(
        "Greek à disséquer",
        list(GREEK_ANALYTICS),
        index=0,
        key="strategy_lab_selected_greek",
    )
    spec = GREEK_ANALYTICS[selected]
    current = _finite(totals.get(spec["key"]))
    sign_reading = spec["positive"] if current > EPS else spec["negative"] if current < -EPS else "Exposition locale proche de zéro ; le profil peut néanmoins devenir important hors du spot courant."

    _render_metric_strip([
        (selected, _format_greek_exposure(current), spec["unit"]),
        ("Signe", "POSITIF" if current > EPS else "NÉGATIF" if current < -EPS else "NEUTRE", sign_reading),
        ("Formule", spec["formula"], "Convention explicite du moteur"),
        ("Hedge", "DYNAMIQUE", spec["hedge"]),
    ])

    knowledge_tabs = st.tabs(["Définition", "Facteurs & signe", "Stratégies", "Limites du modèle"])
    with knowledge_tabs[0]:
        st.info(f"**Définition** — {spec['definition']}\n\n**Lectures et conventions** — {spec['variants']}")
    with knowledge_tabs[1]:
        st.info(f"**Ce qui le fait bouger** — {spec['drivers']}\n\n**Lecture du book maintenant** — {sign_reading}")
    with knowledge_tabs[2]:
        st.info(f"**Structures typiques** — {spec['structures']}\n\n**Action de couverture** — {spec['hedge']}")
    with knowledge_tabs[3]:
        st.warning(spec["caveat"])

    if selected == "Delta":
        _render_delta_lenses(legs, spot, totals, rate, dividend)

    elapsed = st.slider(
        "Temps écoulé pour le diagnostic",
        min_value=0,
        max_value=max(int(dte), 1),
        value=0,
        step=1,
        key="strategy_lab_greek_elapsed",
    )
    spot_grid = np.linspace(0.72, 1.28, 113)
    line_profile = build_greek_profile(
        legs,
        spot,
        selected,
        spot_grid,
        [-5.0, 0.0, 5.0],
        [elapsed],
        rate,
        dividend,
    )
    line_fig = go.Figure()
    palette = {-5.0: "#38bdf8", 0.0: "#f8fafc", 5.0: "#f97316"}
    for shift in (-5.0, 0.0, 5.0):
        subset = line_profile[line_profile["IV shift"] == shift]
        line_fig.add_trace(go.Scatter(
            x=subset["Spot"],
            y=subset["Exposure"],
            name=f"IV {shift:+.0f} pts",
            line=dict(color=palette[shift], width=2),
            hovertemplate="Spot %{x:,.2f}<br>Exposition %{y:+.4g}<extra></extra>",
        ))
    line_fig.add_vline(x=spot, line_dash="dash", line_color="#22c55e")
    line_fig.add_hline(y=0, line_dash="dot", line_color="#64748b")
    line_fig.update_layout(
        height=430,
        margin=dict(l=15, r=15, t=55, b=15),
        paper_bgcolor="#07111c",
        plot_bgcolor="#07111c",
        font=dict(color="#dbeafe"),
        title=f"{selected} selon le spot — trois régimes d'IV · J+{elapsed}",
        xaxis_title="Spot scénario",
        yaxis_title=spec["unit"],
    )
    st.plotly_chart(line_fig, width="stretch", key="strategy_lab_selected_greek_profile")

    heat_profile = build_greek_profile(
        legs,
        spot,
        selected,
        np.linspace(0.82, 1.18, 25),
        np.linspace(-12.0, 12.0, 13),
        [elapsed],
        rate,
        dividend,
    )
    heat_pivot = heat_profile.pivot(index="IV shift", columns="Spot", values="Exposure").sort_index(ascending=False)
    heat_fig = go.Figure(go.Heatmap(
        z=heat_pivot.values,
        x=heat_pivot.columns,
        y=heat_pivot.index,
        colorscale=[[0, "#7f1d1d"], [0.5, "#111827"], [1, "#14532d"]],
        zmid=0,
        colorbar=dict(title=selected),
        hovertemplate="Spot %{x:,.2f}<br>IV %{y:+.0f} pts<br>Exposition %{z:+.4g}<extra></extra>",
    ))
    heat_fig.update_layout(
        height=420,
        margin=dict(l=15, r=15, t=50, b=15),
        paper_bgcolor="#07111c",
        font=dict(color="#dbeafe"),
        title=f"Carte conditionnelle {selected} — spot × choc IV",
        xaxis_title="Spot scénario",
        yaxis_title="Choc IV (points)",
    )
    st.plotly_chart(heat_fig, width="stretch", key="strategy_lab_selected_greek_heatmap")

    contributions = greek_leg_contributions(legs, spot, selected, rate, dividend)
    contrib_fig = go.Figure(go.Bar(
        x=contributions["Contribution"],
        y=contributions["Jambe"],
        orientation="h",
        marker_color=["#22c55e" if value >= 0 else "#ef4444" for value in contributions["Contribution"]],
        hovertemplate="%{y}<br>Contribution %{x:+.4g}<extra></extra>",
    ))
    contrib_fig.update_layout(
        height=max(300, 72 * len(contributions)),
        margin=dict(l=15, r=15, t=45, b=15),
        paper_bgcolor="#07111c",
        plot_bgcolor="#07111c",
        font=dict(color="#dbeafe"),
        title=f"Contribution de chaque jambe au {selected}",
        xaxis_title=spec["unit"],
    )
    st.plotly_chart(contrib_fig, width="stretch", key="strategy_lab_greek_contributions")
    st.dataframe(contributions, width="stretch", hide_index=True)


def _render_cross_greek_analysis(
    legs: Sequence[StrategyLeg],
    spot: float,
    rate: float,
    dividend: float,
) -> None:
    shocks = build_cross_greek_shocks(legs, spot, rate, dividend)
    raw = shocks.pivot(index="Scénario", columns="Greek", values="Variation")
    ordered_scenarios = ["Spot -1%", "Spot +1%", "IV -5 pts", "IV +5 pts", "Temps +1j", "Taux +100bp"]
    raw = raw.reindex(index=ordered_scenarios, columns=list(GREEK_ANALYTICS))
    scales = raw.abs().max(axis=0).replace(0.0, 1.0)
    normalized = raw.divide(scales, axis=1)
    interaction_fig = go.Figure(go.Heatmap(
        z=normalized.values,
        x=normalized.columns,
        y=normalized.index,
        colorscale=[[0, "#7f1d1d"], [0.5, "#111827"], [1, "#14532d"]],
        zmid=0,
        zmin=-1,
        zmax=1,
        colorbar=dict(title="Variation normalisée"),
        customdata=raw.values,
        hovertemplate="%{y}<br>%{x}<br>Variation brute %{customdata:+.4g}<extra></extra>",
    ))
    interaction_fig.update_layout(
        height=430,
        margin=dict(l=15, r=15, t=55, b=15),
        paper_bgcolor="#07111c",
        font=dict(color="#dbeafe"),
        title="Propagation des chocs dans les 11 Greeks",
        xaxis_title="Greek observé",
        yaxis_title="Facteur choqué",
    )
    st.plotly_chart(interaction_fig, width="stretch", key="strategy_lab_cross_greek_heatmap")
    st.caption("Normalisation effectuée Greek par Greek uniquement pour visualiser les changements de signe et de régime ; le survol conserve la variation dans l'unité brute.")

    links = pd.DataFrame([
        {"Risque source": "Delta", "Dérivées qui le déplacent": "Gamma (spot), Vanna (IV), Charm (temps)", "Décision": "Un hedge delta doit être projeté sous les trois facteurs."},
        {"Risque source": "Gamma", "Dérivées qui le déplacent": "Speed (spot), Zomma (IV), Color (temps)", "Décision": "Limiter le gamma conditionnel, pas seulement sa valeur au spot."},
        {"Risque source": "Vega", "Dérivées qui le déplacent": "Vanna (spot), Vomma (IV)", "Décision": "Un vega nul aujourd'hui peut réapparaître après un choc."},
        {"Risque source": "Theta", "Dérivées qui le déplacent": "Charm (delta), Color (gamma)", "Décision": "Le carry modifie le hedge et la convexité à mesure que l'échéance approche."},
        {"Risque source": "Rho", "Dérivées qui le déplacent": "Forward, dividendes, borrow et courbe", "Décision": "Utiliser les forwards/courbes de maturité en production."},
    ])
    st.dataframe(links, width="stretch", hide_index=True)
    with st.expander("Matrice brute des variations", expanded=False):
        st.dataframe(raw, width="stretch")


def _render_greek_cockpit(
    legs: Sequence[StrategyLeg],
    spot: float,
    dte: int,
    rate: float,
    dividend: float,
) -> None:
    totals = aggregate_strategy_greeks(legs, spot, 0, 0.0, rate, dividend)
    st.markdown("#### Greek Intelligence Center — 11 sensibilités, une décision par risque")
    _render_metric_strip([
        ("Delta unités", f"{totals['delta']:+,.1f}", "Actions équivalentes"),
        ("Dollar delta", _money(totals["dollar_delta"]), "Exposition directionnelle"),
        ("Gamma P&L 1%", _money(totals["dollar_gamma_1pct"]), "½Γ(1% spot)²"),
        ("Vega", _money(totals["vega_1vol"]), "+1 vol point"),
        ("Theta", _money(totals["theta_1d"]), "1 jour écoulé"),
        ("Rho", _money(totals["rho_100bp"]), "+100 bps"),
    ])

    greek_tabs = st.tabs(["Vue des 11 Greeks", "Analyse individuelle", "Interactions & hedge"])
    with greek_tabs[0]:
        _render_greek_overview(legs, spot, totals, rate, dividend)
    with greek_tabs[1]:
        _render_selected_greek_analysis(legs, spot, dte, totals, rate, dividend)
    with greek_tabs[2]:
        _render_cross_greek_analysis(legs, spot, rate, dividend)

    st.caption(
        "Moteur local Black-Scholes-Merton à IV plate par jambe. Ces diagnostics modélisent sensibilité, hedge et interactions, "
        "mais pas exercice américain, dividendes discrets, borrow, smile dynamique ni liquidité de re-hedge."
    )


def _render_strategy_selector(
    directional_view: str,
    volatility_view: str,
    metrics: Mapping[str, Any],
    dte: int,
    liquidity_score: float,
    selected_template: str,
) -> None:
    ranked = rank_strategy_templates(directional_view, volatility_view, metrics.get("iv_premium_20"), dte, liquidity_score)
    best = ranked.iloc[0]
    _render_metric_strip([
        ("Meilleur fit", str(best["Stratégie"]), f"{best['Fit']:.0f}/100"),
        ("Stratégie active", selected_template, f"{float(ranked.loc[ranked['Stratégie'] == selected_template, 'Fit'].iloc[0]):.0f}/100"),
        ("Prime IV / RV", f"{_finite(metrics.get('iv_premium_20')):+.1%}", "Signal de valeur, pas forecast"),
        ("DTE", str(dte), "Court terme" if dte < 7 else "Maturité exploitable"),
    ])
    chart = ranked.head(10).sort_values("Fit")
    fig = go.Figure(go.Bar(x=chart["Fit"], y=chart["Stratégie"], orientation="h", marker_color=["#22d3ee" if name == selected_template else "#334155" for name in chart["Stratégie"]], text=chart["Fit"].map(lambda x: f"{x:.0f}"), textposition="outside"))
    fig.update_layout(height=430, margin=dict(l=15, r=35, t=35, b=15), paper_bgcolor="#07111c", plot_bgcolor="#07111c", font=dict(color="#dbeafe"), xaxis=dict(range=[0, 105]), xaxis_title="Fit mécanique /100")
    st.plotly_chart(fig, width="stretch", key="strategy_lab_ranker")
    display = ranked.head(10).copy()
    display["Fit"] = display["Fit"].map(lambda value: f"{value:.0f}/100")
    st.dataframe(display, width="stretch", hide_index=True)
    st.caption("Le classement traduit uniquement la vue directionnelle/vol, la prime IV‑RV, le DTE et la liquidité. Il ne remplace ni forecast, ni contraintes portefeuille, ni marge broker.")


def render_strategy_lab(
    ticker: str,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    expiration: str,
    metrics: Mapping[str, Any],
    macro_summary: Mapping[str, Any],
    data_context: Optional[Mapping[str, Any]] = None,
) -> None:
    """Render the decision-centric multi-leg strategy workspace."""
    st.subheader("Strategy & Risk Lab")
    st.caption("Chaîne → jambes → coût exécutable → payoff → scénarios → Greeks → décision. Aucun ordre n'est transmis.")
    if calls is None or puts is None or (calls.empty and puts.empty):
        st.warning("Chaîne options indisponible : impossible de construire une stratégie live.")
        return

    dte = max(int(_finite(metrics.get("dte"), 1)), 1)
    atm_iv = max(_finite(metrics.get("atm_iv"), 0.25), 0.03)
    strikes = _available_strikes(calls, puts)
    if not strikes:
        st.warning("Aucun strike exploitable dans la chaîne sélectionnée.")
        return

    top = st.columns([1.25, 0.85, 0.85, 0.85])
    with top[0]:
        template = st.selectbox("Structure", STRATEGY_TEMPLATES, index=STRATEGY_TEMPLATES.index("Iron Condor"), key="strategy_lab_template")
    with top[1]:
        directional_view = st.selectbox("Vue spot", ["Baissier", "Neutre / range", "Haussier"], index=1, key="strategy_lab_direction")
    with top[2]:
        volatility_view = st.selectbox("Vue volatilité", ["Expansion", "Stable", "Compression"], index=1, key="strategy_lab_vol_view")
    with top[3]:
        price_mode = st.selectbox("Prix d'entrée", ["Exécutable (ask/bid)", "Mid indicatif"], index=0, key="strategy_lab_price_mode")

    controls = st.columns([1.15, 0.85, 0.85, 0.85])
    center_default = min(range(len(strikes)), key=lambda idx: abs(strikes[idx] - spot))
    with controls[0]:
        center = st.select_slider("Strike central", options=strikes, value=strikes[center_default], key="strategy_lab_center")
    with controls[1]:
        width_steps = st.slider("Largeur corps (pas)", 1, 10, 2, key="strategy_lab_width")
    with controls[2]:
        wing_steps = st.slider("Largeur ailes (pas)", 1, 10, 2, key="strategy_lab_wings")
    with controls[3]:
        contracts = st.number_input("Lots", min_value=1, max_value=100, value=1, step=1, key="strategy_lab_contracts")

    seed_legs = build_template_legs(template, calls, puts, spot, dte, atm_iv, center, width_steps, wing_steps, int(contracts), price_mode)
    seed_frame = legs_to_frame(seed_legs)
    editor_key = f"strategy_lab_legs_{ticker}_{expiration}_{template}_{center}_{width_steps}_{wing_steps}_{contracts}_{price_mode}"
    with st.expander("Jambes — édition institutionnelle", expanded=True):
        edited = st.data_editor(
            seed_frame,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key=editor_key,
            column_config={
                "Side": st.column_config.SelectboxColumn(options=["Long", "Short"]),
                "Type": st.column_config.SelectboxColumn(options=["Call", "Put", "Action"]),
                "Quantité": st.column_config.NumberColumn(min_value=1, step=1),
                "Strike": st.column_config.NumberColumn(format="%.2f"),
                "Prime": st.column_config.NumberColumn(format="$%.4f"),
                "IV %": st.column_config.NumberColumn(format="%.2f"),
                "DTE": st.column_config.NumberColumn(min_value=0, step=1),
                "Bid": st.column_config.NumberColumn(format="$%.4f"),
                "Ask": st.column_config.NumberColumn(format="$%.4f"),
            },
        )
        st.caption("Les structures sont préremplies avec les strikes disponibles. En mode exécutable, les achats partent à l'ask et les ventes au bid ; modifiez toute jambe pour tester une combinaison sur mesure.")
    legs = frame_to_legs(edited, dte, atm_iv)
    if not legs:
        st.warning("Ajoutez au moins une jambe.")
        return

    with st.expander("Hypothèses de modèle et scénario", expanded=False):
        model_cols = st.columns(4)
        with model_cols[0]:
            rate = st.number_input("Taux sans risque", min_value=-0.05, max_value=0.25, value=0.045, step=0.0025, format="%.4f", key="strategy_lab_rate")
        with model_cols[1]:
            dividend = st.number_input("Rendement dividende", min_value=0.0, max_value=0.20, value=0.0, step=0.0025, format="%.4f", key="strategy_lab_dividend")
        with model_cols[2]:
            drift = st.number_input("Drift probabilité", min_value=-0.50, max_value=0.50, value=0.0, step=0.01, format="%.3f", key="strategy_lab_drift")
        with model_cols[3]:
            horizon = st.slider("Horizon (jours)", 0, dte, min(max(dte // 3, 1), dte), key="strategy_lab_horizon")
        shock_cols = st.columns(2)
        with shock_cols[0]:
            spot_shock = st.slider("Choc spot", -0.35, 0.35, 0.0, 0.01, format="%+.0f%%", key="strategy_lab_spot_shock")
        with shock_cols[1]:
            iv_shift = st.slider("Choc IV (vol points)", -40.0, 40.0, 0.0, 1.0, key="strategy_lab_iv_shock")

    quality = quote_quality(legs)
    tabs = st.tabs(["Payoff & Scénarios", "Greek Intelligence · 11", "Strategy Selector", "Risk & Execution"])
    with tabs[0]:
        _render_payoff_and_scenarios(legs, spot, dte, atm_iv, metrics, horizon, spot_shock, iv_shift, rate, dividend, drift)
    with tabs[1]:
        _render_greek_cockpit(legs, spot, dte, rate, dividend)
    with tabs[2]:
        _render_strategy_selector(directional_view, volatility_view, metrics, dte, quality["score"], template)
    with tabs[3]:
        summary = summarize_strategy(legs, spot, dte, atm_iv, drift)
        st.markdown("#### Ticket de risque et exécution")
        source = dict(data_context or {})
        source_value = f"{source.get('provider', 'Source non qualifiée')} · {source.get('recency', 'UNKNOWN')}"
        source_status = "Live qualifié" if source.get("status") == "ok" and source.get("recency") == "REAL-TIME" else "À contrôler"
        source_action = "Revalider NBBO et tailles avant ordre" if source.get("status") == "ok" else "Rétablir une source licenciée avant exécution"
        risk_rows = [
            {"Contrôle": "Liquidité quotes", "Valeur": f"{quality['score']:.0f}/100", "Statut": quality["state"], "Action": "Ordres limites / travailler les jambes" if quality["score"] < 75 else "Quotes utilisables avec contrôle live"},
            {"Contrôle": "Coût spread aller", "Valeur": _money(quality["spread_cost"]), "Statut": "Inclus via bid/ask", "Action": "Comparer au profit attendu et aux commissions"},
            {"Contrôle": "Risque de queue", "Valeur": summary.right_tail, "Statut": "ALERTE" if math.isinf(summary.max_loss) else "Borné", "Action": "Ajouter une aile" if math.isinf(summary.max_loss) else "Vérifier le sizing"},
            {"Contrôle": "DTE / assignment", "Valeur": f"{dte} jours", "Statut": "Court" if dte < 7 else "Standard", "Action": "Contrôler exercice anticipé/dividende sur jambes courtes"},
            {"Contrôle": "Données", "Valeur": source_value, "Statut": source_status, "Action": source_action},
            {"Contrôle": "Modèle", "Valeur": "BSM européen", "Statut": "Proxy", "Action": "Arbre américain + dividendes discrets pour production"},
        ]
        st.dataframe(pd.DataFrame(risk_rows), width="stretch", hide_index=True)
        if any(leg.side < 0 for leg in legs):
            st.warning("Les jambes courtes portent un risque d'assignation anticipée. Le payoff théorique ne représente ni marge broker, ni borrow, ni pin/assignment operational risk.")
        if math.isinf(summary.max_loss):
            st.error("Perte théorique non bornée détectée sur la queue droite. La structure n'est pas validable sans limite de risque, marge et règle de sortie explicites.")
        st.download_button(
            "Exporter le ticket stratégie CSV",
            edited.to_csv(index=False).encode("utf-8"),
            file_name=f"strategy_ticket_{ticker}_{expiration}.csv",
            mime="text/csv",
            key="strategy_lab_export",
        )
        st.caption(f"Expiration {expiration} · Spot {spot:,.2f} · ATM IV {atm_iv:.2%} · Tape futures {macro_summary.get('tape_state', 'N/A')}. Les probabilités sont des hypothèses de distribution, jamais une fréquence garantie.")


__all__ = [
    "StrategyLeg",
    "StrategySummary",
    "aggregate_strategy_greeks",
    "black_scholes_greeks",
    "black_scholes_price",
    "build_cross_greek_shocks",
    "build_greek_profile",
    "build_template_legs",
    "greek_leg_contributions",
    "pnl_attribution",
    "quote_quality",
    "rank_strategy_templates",
    "render_strategy_lab",
    "scenario_matrix",
    "strategy_mark_pnl",
    "strategy_pnl_at_expiry",
    "summarize_strategy",
]

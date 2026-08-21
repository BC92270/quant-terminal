# Risk Monitor institutionnel

Le Risk Monitor est un cockpit de contrôle pour une position unique. Il combine
risque de marché, risque de queue, risque de modèle, capacité de liquidation,
sizing, scénarios et validation. Il ne calcule pas un capital réglementaire et
ne remplace ni un moteur de portefeuille agrégé, ni un système d'exécution.

## Architecture

- `risk_control/engine.py` contient uniquement des calculs purs, déterministes
  et testables. Il ne dépend pas de Streamlit.
- `risk_control/advanced.py` orchestre les challengers GJR-GARCH Student-t,
  Markov/EVT, les intervalles bootstrap, la pondération hors échantillon et le
  contrat de décomposition factorielle.
- `risk_control/data_fabric.py` déclare les contrats de données et active les
  enrichissements NBBO/options dès qu'une clé compatible est configurée, sans
  exposer le secret dans les logs ou exports.
- `risk_monitor.py` adapte les résultats au trading plan existant et rend les
  vues interactives.
- `market_data_gateway.py` attache la provenance dans
  `price_data.attrs["data_context"]`. Le Risk Monitor conserve et affiche ce
  lineage, y compris les fallbacks et la récence non garantie.
- `tests/test_risk_control.py` couvre les conventions de queue, le stress
  inverse, la liquidité, les drawdowns, la validation VaR et la provenance.

## Mesures disponibles

### Risque de queue

Le même horizon et le même niveau de confiance sont appliqués à huit
benchmarks et challengers gouvernés :

1. simulation historique sur rendements glissants réels ;
2. modèle gaussien paramétrique sur log-rendements ;
3. simulation Student-t calibrée ;
4. filtered historical simulation avec volatilité EWMA.
5. FHS conditionnelle calibrée par GJR-GARCH Student-t ;
6. simulation de régimes Markov calme/volatile/crise ;
7. injection de queue EVT dans les scénarios ;
8. benchmark pondéré selon la couverture conditionnelle observée hors
   échantillon.

La VaR est le quantile défavorable. L'Expected Shortfall est la moyenne des
pertes au-delà de ce quantile. Les valeurs de rendement sont négatives dans le
cockpit ; leur conversion en dollars utilise le notionnel saisi. La dispersion
des ES est affichée comme un indicateur explicite de risque de spécification.

Une couche EVT Peaks over Threshold réutilise le moteur Monte Carlo existant.
Elle n'est activée qu'avec au moins 120 rendements. Son seuil s'adapte à la
profondeur de l'historique pour viser environ 30 excès, sans descendre sous le
90e percentile ni dépasser le 95e. Elle affiche l'éligibilité du fit, le
paramètre de forme, le test KS, la stabilité du seuil et 80 réplications
bootstrap. Elle reste un diagnostic challenger et ne remplace pas l'ES
principale.

Le laboratoire avancé ajoute également 240 réplications moving-block pour
mesurer l'incertitude de VaR/ES. Les intervalles sont affichés à côté des
estimations ponctuelles : un historique court ne peut donc plus produire une
fausse impression de précision sans avertissement visible.

### Validation

Deux VaR journalières sont recalculées hors échantillon : historique glissante
et gaussienne EWMA. Le cockpit produit :

- le nombre et le taux d'exceptions ;
- le test de couverture inconditionnelle de Kupiec ;
- le test d'indépendance de Christoffersen ;
- le test de couverture conditionnelle ;
- une série temporelle des exceptions.

Moins de 100 observations de validation entraînent le statut `LIMITED`. Une
p-value faible entraîne `WARNING` ou `FAIL`; le résultat ne peut donc pas être
présenté comme validé sur une fenêtre trop courte.

Le benchmark pondéré n'utilise que ces deux historiques de prévision. Son poids
combine l'erreur de taux d'exception et la p-value de couverture
conditionnelle. Les modèles GJR, Markov et EVT restent `CHALLENGER` ou
`RESEARCH` tant qu'une validation walk-forward compatible n'est pas attachée.

### Position, liquidité et stress inverse

Les contrôles de position utilisent le NAV, le notionnel, le sens, une limite
de perte en points de base de NAV et une participation maximale à l'ADV.

- `VaR capital` et `ES capital` convertissent les pertes de rendement en dollars.
- Le notionnel maximal est calculé séparément par le stop et par l'ES ; la
  contrainte la plus prudente devient la limite liante.
- La capacité de liquidation utilise le dollar ADV médian et le taux de
  participation choisi.
- L'impact de marché est un proxy racine carrée transparent
  (`0.5 × vol quotidienne × sqrt(position / ADV)`), jamais une cotation.
- Le stress inverse part de la limite de perte et résout le choc de l'actif qui
  la ferait franchir.

Les scénarios incluent un choc utilisateur, les pires rendements historiques
1/5/20 jours, un choc de volatilité, l'ES prudente et les deux stops. Le coût de
liquidité est ajouté à chaque P&L stressé.

## Gouvernance des données

La qualité tient compte du nombre d'observations, de la date du dernier point,
des doublons, des prix inchangés et de la couverture volume. Une source
`fallback`, `reference`, différée ou à récence non spécifiée déclenche toujours
une alerte de provenance distincte, même si la série est exploitable.

### Data Fabric

La vue `Data Fabric` expose l'état de chaque contrat sans jamais afficher la
valeur d'une clé :

- `TWELVE_DATA_API_KEY` / `ALPHA_VANTAGE_API_KEY` : historique OHLCV ;
- `TRADIER_API_TOKEN`, `MASSIVE_API_KEY` ou `THETADATA_API_KEY` : cotation,
  chaîne options, IV, Greeks et open interest selon entitlement ;
- `DATABENTO_API_KEY` : contrat prêt pour profondeur de marché et futures ;
- `FRED_API_KEY` et gateway partagé : contrat prêt pour matrice factorielle ;
- payload Portfolio Lab : contrat prêt pour positions, hedges, Greeks et limites.

Tradier, Massive et ThetaData sont auto-routés pour l'enrichissement options.
En l'absence de clé ou d'entitlement, le moteur conserve l'OHLCV et marque le
bloc comme `READY FOR KEY` ou `CONFIGURED NO DATA` au lieu d'inventer des
données.

## Références de conception

Le cockpit s'inspire de principes publics, sans revendiquer leur conformité
réglementaire :

- le [Basel Framework MAR10](https://www.bis.org/basel_framework/chapter/MAR/10.htm)
  pour les définitions VaR, ES, horizon de liquidité et backtesting ;
- les [Basel stress testing principles](https://www.bis.org/bcbs/publ/d450.htm)
  pour l'intégration des scénarios à la gouvernance et aux décisions ;
- la [Federal Reserve SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
  pour la validation proportionnée, le monitoring, les limites et la
  communication des faiblesses de modèles ;
- la [SEC Rule 22e-4](https://www.sec.gov/rules-regulations/2016/10/investment-company-liquidity-risk-management-programs)
  comme référence de conception pour l'analyse de profondeur, de taille
  anticipée et de liquidité.

## Limites connues

- Le contrôle principal reste mono-position. Le calcul de décomposition
  factorielle est opérationnel, mais attend une matrice de rendements alignés ;
  les concentrations et hedges agrégés restent la responsabilité de Portfolio
  Lab / Correlation Matrix.
- Le volume de clôture ne remplace pas un carnet d'ordres, un spread ni une
  courbe d'impact propriétaire.
- Les distributions ajustées sur un an peuvent manquer des régimes de crise.
  Il faut étendre la période pour les décisions à forte matérialité.
- Les chemins Monte Carlo existants ne sont affichés que si l'horizon demandé
  correspond réellement aux données disponibles ; aucun horizon n'est
  réétiqueté silencieusement.
- Tous les exports contiennent les hypothèses afin qu'un résultat puisse être
  reproduit et challengé.

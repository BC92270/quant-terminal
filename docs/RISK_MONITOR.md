# Risk Monitor institutionnel

Le Risk Monitor est un cockpit de contrôle pour une position unique. Il combine
risque de marché, risque de queue, risque de modèle, capacité de liquidation,
sizing, scénarios et validation. Il ne calcule pas un capital réglementaire et
ne remplace ni un moteur de portefeuille agrégé, ni un système d'exécution.

## Architecture

- `risk_control/engine.py` contient uniquement des calculs purs, déterministes
  et testables. Il ne dépend pas de Streamlit.
- `risk_monitor.py` adapte les résultats au trading plan existant et rend les
  vues interactives.
- `market_data_gateway.py` attache la provenance dans
  `price_data.attrs["data_context"]`. Le Risk Monitor conserve et affiche ce
  lineage, y compris les fallbacks et la récence non garantie.
- `tests/test_risk_control.py` couvre les conventions de queue, le stress
  inverse, la liquidité, les drawdowns, la validation VaR et la provenance.

## Mesures disponibles

### Risque de queue

Le même horizon et le même niveau de confiance sont appliqués à quatre
challengers :

1. simulation historique sur rendements glissants réels ;
2. modèle gaussien paramétrique sur log-rendements ;
3. simulation Student-t calibrée ;
4. filtered historical simulation avec volatilité EWMA.

La VaR est le quantile défavorable. L'Expected Shortfall est la moyenne des
pertes au-delà de ce quantile. Les valeurs de rendement sont négatives dans le
cockpit ; leur conversion en dollars utilise le notionnel saisi. La dispersion
des ES est affichée comme un indicateur explicite de risque de spécification.

Une couche EVT Peaks over Threshold réutilise le moteur Monte Carlo existant.
Elle n'est activée qu'avec au moins 120 rendements et affiche l'éligibilité du
fit, le nombre d'excès, le paramètre de forme, le test KS et la stabilité du
seuil. Elle reste un diagnostic challenger et ne remplace pas l'ES principale.

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

- Le moteur est mono-position. Les corrélations, concentrations et hedges
  cross-asset doivent être contrôlés dans Portfolio Lab / Correlation Matrix.
- Le volume de clôture ne remplace pas un carnet d'ordres, un spread ni une
  courbe d'impact propriétaire.
- Les distributions ajustées sur un an peuvent manquer des régimes de crise.
  Il faut étendre la période pour les décisions à forte matérialité.
- Les chemins Monte Carlo existants ne sont affichés que si l'horizon demandé
  correspond réellement aux données disponibles ; aucun horizon n'est
  réétiqueté silencieusement.
- Tous les exports contiennent les hypothèses afin qu'un résultat puisse être
  reproduit et challengé.

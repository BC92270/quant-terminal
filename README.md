# Quant Terminal

Terminal Streamlit multi-domaine pour la recherche quantitative, le risque, la
construction de portefeuille et l'intelligence de marché.

## Démarrage rapide

Prérequis : Python 3.11 ou 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

Le profil standard reste volontairement léger. Les runtimes neuronaux, beaucoup
plus lourds, ne sont nécessaires que pour les challengers PyTorch et TensorFlow :

```bash
python -m pip install -r requirements-ml.txt
```

## Architecture

`app.py` compose le shell et route vers des façades de compatibilité. La logique
métier nouvelle doit vivre dans les packages de domaine :

| Domaine | Package principal |
| --- | --- |
| Backtests institutionnels | `backtest_institutional/` |
| Intelligence entreprise | `company_intelligence/` |
| Corrélations et dépendances | `correlation_matrix_section/` |
| Fixed income et crédit | `fixed_income/` |
| Psychologie de marché | `market_psychology/` |
| Recherche ML | `ml_lab/` |
| Momentum et tendance | `momentum_trend/` |
| Monte Carlo et dérivés | `monte_carlo/` |
| Contrôle des risques | `risk_control/` |
| Comité Quant AI | `quant_ai/` |
| Intelligence géopolitique | `worldmonitor/` |

Le routeur multi-actifs s'appuie sur `security_master.py` pour fusionner le
catalogue éditorial avec les identités fournisseur mises en cache dans SQLite.
Une synchronisation SEC peut être lancée avec
`python scripts/sync_security_master.py` ; OpenFIGI reste la couche de
symbologie mondiale optionnelle.

Les anciens renderers encore requis sont isolés dans `legacy/`. Ils ne sont pas
une destination autorisée pour de nouvelles fonctionnalités. Voir
`docs/ARCHITECTURE.md` pour les dépendances et les règles de frontières.

## Validation

```bash
python scripts/audit_repository.py
python -m compileall -q .
pytest --collect-only -q
pytest -q --disable-warnings
python scripts/validate_fixed_income.py
```

La CI exécute ces contrôles sur chaque pull request et sur `main`. Les tests des
backends neuronaux sont automatiquement ignorés si le profil ML optionnel n'est
pas installé.

## État local et secrets

- Les caches d'exécution vivent dans les répertoires cachés `.quant_*` ou dans
  les emplacements définis par variables d'environnement ; ils ne sont jamais
  versionnés.
- Les secrets restent dans l'environnement ou `.streamlit/secrets.toml`.
- Les sauvegardes, archives, patchs, bytecodes et bases locales sont ignorés.
- Les snapshots de référence versionnés doivent vivre sous le package qui les
  consomme, dans un répertoire `data/` clairement identifié.

Copiez les seules variables utiles depuis `.env.providers.example`, puis
contrôlez la couverture sans exposer les valeurs avec
`python scripts/audit_data_providers.py`. Les flux historiques routés utilisent
une passerelle explicite Twelve Data → Alpha Vantage → source publique adaptée
à l'actif → Yahoo ; Options utilise ThetaData → Massive → Tradier → Yahoo.

## Documentation

- `docs/ARCHITECTURE.md` : frontières, flux et règles de dépendances.
- `docs/REPOSITORY_AUDIT.md` : audit structurel et décisions de nettoyage.
- `docs/WORLDMONITOR_AUDIT.md` : architecture WorldMonitor.
- `docs/WORLDMONITOR_INSTITUTIONAL_RESEARCH.md` : sources et trajectoire quant.
- `docs/QUANT_AI_ARCHITECTURE.md` : architecture du comité Quant AI.
- `docs/fixed_income_runbook.md` : exploitation du cœur fixed income.
- `docs/SECURITY_MASTER.md` : identités, fournisseurs et synchronisation du catalogue.
- `docs/DATA_PROVIDERS.md` : matrice par section, clés optionnelles, fallbacks et provenance.
- `docs/RISK_MONITOR.md` : modèles, contrôles, validation, liquidité et limites du Risk Monitor.

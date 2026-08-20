# Audit structurel du dépôt

Date de référence : 20 août 2026.

## Périmètre observé

- 310 fichiers versionnés dans le snapshot de sécurité.
- 279 fichiers Python et environ 326 000 lignes de Python hors caches.
- Dix domaines fonctionnels majeurs, avec un shell Streamlit partagé.
- Des monolithes historiques importants à la racine, mais aussi des packages
  récents déjà bien séparés (`fixed_income`, `monte_carlo`, `quant_ai`,
  `worldmonitor`, etc.).

## Anomalies corrigées

| Anomalie | Correction |
| --- | --- |
| 1 855 fichiers non suivis, principalement caches et bytecodes | Politique `.gitignore` et `.dockerignore` renforcée |
| Deux `test_core.py` strictement identiques | Copie racine supprimée |
| Deux `test_quant_ai_core.py` incompatibles | Ancienne suite V2 supprimée, suite V3 conservée |
| Imports `tests.test_v2_3` inexistants | Sous-suite déclarée comme package et imports rendus absolus |
| Install standard forçant PyTorch et TensorFlow | Profil lourd déplacé vers `requirements-ml.txt` |
| Dépendances réellement importées absentes du manifeste | `beautifulsoup4`, `scipy`, `scikit-learn` et `statsmodels` déclarés |
| Dépendances Quant AI déclarées mais jamais importées | Manifestes obsolètes supprimés |
| Snapshot entreprise rangé dans `data_cache/` | Seed immutable déplacé vers `company_intelligence/data/` |
| Renderer WorldMonitor historique à la racine | Runtime isolé sous `legacy/`, derrière l'adapter packagé |
| Scripts one-shot d'intégration déjà appliqués | Scripts et fichiers de backup supprimés du code actif |
| Configuration `pyproject.toml` limitée au seul fixed income | Configuration recentrée sur les outils du dépôt complet |
| CI limitée à un seul domaine | Gate globale de compilation, collecte et tests |

## Risques encore suivis

Les grands fichiers historiques ne doivent pas être découpés mécaniquement :
`backtest_lab.py`, `market_intelligence.py`, `macro_central_bank_lab.py`,
`portfolio_lab.py`, `ml_lab/research_lab.py` et le runtime WorldMonitor de
compatibilité possèdent un large état implicite. Leur réduction exige des tests
de caractérisation par sous-domaine avant chaque extraction.

La règle active est donc : aucun nouveau calcul dans ces façades, extraction
progressive vers les packages, puis suppression du code devenu réellement
inaccessible. Cela évite les chevauchements sans casser les parcours existants.

## Validation du nettoyage

- Audit structurel : 0 artefact interdit, 0 erreur de syntaxe, 0 doublon exact,
  0 cycle entre domaines.
- Suite large hors Corrélation : 284 tests réussis, 6 tests neuronaux ignorés
  lorsque le profil ML optionnel n'est pas installé.
- Quant AI et Psychologie ciblés : 21 tests réussis.
- WorldMonitor et Company Intelligence ciblés : 13 tests réussis.
- Fixed income ciblé : 18 tests réussis et gate opérationnelle valide.
- Régressions d'ensemble et de market pack : 7 tests réussis après correction.

La sous-suite Corrélation ne peut pas être exécutée dans l'environnement local
historique, qui combine `statsmodels 0.14.0` avec `SciPy 1.17`. Le manifeste
déclare désormais explicitement les deux dépendances ; la CI les résout dans un
environnement Python 3.12 neuf avant la collecte globale.

# Architecture du Quant Terminal

## Flux principal

```text
Streamlit / app.py
        |
        +-- façades de workspace à la racine (*_lab.py, *_credit.py, bridges)
        |       |
        |       +-- packages de domaine
        |               |
        |               +-- calculs, contrats, données, gouvernance, UI locale
        |
        +-- shell partagé (ui_*.py, asset_class_router.py)

packages de domaine --> fournisseurs externes / snapshots versionnés
packages de domaine --> caches locaux ignorés par Git
```

## Règles de frontières

1. `app.py` route et compose. Aucun nouveau moteur quantitatif ne doit y être
   ajouté.
2. Une façade racine conserve une API stable pour le shell, mais délègue les
   calculs au package du même domaine.
3. Les packages de domaine ne doivent pas importer `app.py` ni une autre façade
   d'interface.
4. Les imports inter-domaines passent par les API publiques des packages ; les
   imports de fonctions privées (`_nom`) restent internes au domaine.
5. `legacy/` est une quarantaine de compatibilité. Aucun nouveau développement
   ne doit y entrer.
6. `scripts/` contient uniquement des commandes explicites et reproductibles.
   Un script ne s'exécute jamais à l'import.
7. `tests/` est un package afin de garantir des noms de modules uniques dans les
   sous-suites.
8. Les caches, bases, journaux, secrets, archives et sauvegardes ne sont jamais
   des sources de vérité Git.

## Propriété des données

- `worldmonitor/data/` contient des assets compilés, versionnés et vérifiés par
  manifeste.
- `company_intelligence/data/` contient uniquement les seeds de référence
  empaquetés. Le cache mutable vit dans `.company_intelligence_cache/`.
- Les autres données générées vivent sous `.quant_*` ou dans un chemin défini
  par l'environnement.

## Dépendances d'exécution

- `requirements.txt` : terminal standard et ML classique.
- `requirements-ml.txt` : profil optionnel PyTorch/TensorFlow.
- `requirements-dev.txt` : tests et couverture.

Cette séparation évite de télécharger plusieurs runtimes neuronaux lors d'un
simple démarrage du terminal ou d'un job CI sans Deep Learning.

## Dette structurelle contrôlée

Plusieurs façades historiques restent volumineuses. Elles sont conservées tant
que leur comportement n'est pas entièrement caractérisé. La stratégie de
migration est incrémentale : écrire les tests de caractérisation, extraire un
sous-domaine vers un package, remplacer la façade par une délégation, puis
supprimer uniquement le code rendu inaccessible.

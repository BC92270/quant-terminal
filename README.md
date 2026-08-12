# Quant Terminal

Terminal Streamlit d'analyse quant et géopolitique.

## WorldMonitor

Le runtime unique vit dans `worldmonitor/`. Il charge des actifs locaux
versionnés et ne dépend pas des ZIP de référence : 134 couches, 2 159 objets
statiques, 195 profils pays, 19 séries officielles Banque mondiale et modèle
structurel `WM-IQ 1.0` avec couverture et incertitude.

```bash
streamlit run app.py
python -m unittest tests.test_worldmonitor_bridge_adapter tests.test_worldmonitor_package -v
```

Reconstruction explicite des actifs (développement uniquement) :

```bash
python scripts/fetch_worldbank_snapshot.py
python scripts/build_worldmonitor_assets.py --sources ../sources
```

Voir `docs/WORLDMONITOR_AUDIT.md` pour l'architecture livrée et
`docs/WORLDMONITOR_INSTITUTIONAL_RESEARCH.md` pour la trajectoire des sources et
du moteur quant.

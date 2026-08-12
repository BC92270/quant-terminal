# WorldMonitor JARVIS V8 — architecture livrée

## Runtime unique

`worldmonitor/` est désormais l'autorité produit. `worldmonitor_bridge_v211.py`
reste seulement un nom d'import compatible avec l'application existante. Le
runtime ne recherche, n'ouvre et ne parse aucun ZIP.

Les archives de référence sont consommées exclusivement par
`scripts/build_worldmonitor_assets.py`. Le résultat versionné est :

- `static_objects.json.gz` : 2 159 objets, 61 layers renseignés ;
- `country_atlas.json.gz` : 195 profils et leur provenance complète ;
- `world_bank_wdi.json.gz` : 19 séries officielles, une observation récente
  par économie ;
- `layer_registry.json` : 134 layers, sans suppression des extensions ;
- `source_manifest.json` : hashes SHA-256, date de build, couverture et hashes
  des cinq archives sources.

Le manifest atteste `zip_runtime_dependency=false`.

## Carte et performance

Le serveur conserve l'atlas intégral. Une vue de rendu déterministe est créée
pour Plotly `Scattergeo`, qui repose sur SVG :

- plafond global par défaut : 1 180 points ;
- plafond par layer statique : 170 ;
- plafond par layer live : 220 ;
- conservation de toutes les lignes et polygones ;
- au moins trois points par layer avant allocation du budget restant ;
- sélection spatiale par cellules adaptatives, puis sévérité/confiance.

Benchmark local reproductible, atlas de référence :

| Mesure | Avant | V8 |
|---|---:|---:|
| Scan/parsing statique froid | ~8,29 s | ~0,05 s |
| Objets dans l'atlas | 2 159 | 2 159 |
| Points transmis au SVG | 1 944 | 1 180 |
| Géométries linéaires/polygones | 215 | 215 |

Les plafonds sont ajustables par variables d'environnement, sans rebuild.

## Country Intelligence

L'atlas contient 195 pays/territoires cartographiés. Le snapshot officiel
Banque mondiale renseigne au moins un indicateur pour 193 profils ; 193 ont un
score comparable. La médiane est de 15 observations sourcées par profil.

Le modèle `WM-IQ 1.0` calcule un risque structurel distinct de l'intensité live :

- stress macro : croissance, inflation, chômage, dette publique disponible ;
- exposition externe : importations, commerce, dépendance énergétique ;
- capacité adaptative : revenu, électricité, numérique, réserves ;
- ressources/concentration : agriculture et urbanisation.

Chaque résultat expose couverture, fraîcheur, confiance, intervalle
d'incertitude, score par pilier et facteurs dominants. Aucune donnée pays
manquante n'est remplacée par un tirage pseudo-aléatoire. Le drawer affiche les
observations officielles avec libellé, code et millésime, les exporte avec le
contexte quant, et dérive quatre canaux explicables (macro, externe, capacité
adaptative, ressources) lorsque le profil ne possède pas déjà un modèle plus
détaillé. Les valeurs `0` historiques stockées sous forme de texte ne peuvent
plus masquer le score structurel.

Deux couches pays sont réellement alimentées :

- `ciiChoropleth` : risque structurel comparable ;
- `resilienceScore` : capacité adaptative, activable dans le drawer.

## Maillage de sources

Le catalogue typé recense 23 fournisseurs et sépare quatre états : `active`,
`snapshot`, `adapter`, `roadmap`. Une source sans clé ou sans intégration n'est
jamais comptée comme active.

Le chargement live actif reste borné et parallèle : USGS, GDACS, NASA EONET,
Google News RSS, GDELT, ACLED, NASA FIRMS, NewsAPI et OpenSky. Les secrets
restent exclusivement côté serveur.

## Garanties testées

- aucun import `zipfile` dans `worldmonitor/` ;
- hashes des quatre actifs contrôlés contre le manifest ;
- 195 profils, provenance WDI, score/confiance bornés et missingness explicite ;
- toutes les géométries et tous les layers ponctuels représentés après budget ;
- fonctions de décroissance temporelle, corroboration, contagion spatiale et
  propagation réseau déterministes ;
- contrat mono-runtime et parité des layers maintenus.

La suite dédiée contient 11 tests et la validation navigateur couvre également
la recherche/activation de layer, les projections 2D/3D et le drawer pays.

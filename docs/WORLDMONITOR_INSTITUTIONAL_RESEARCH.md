# WorldMonitor institutionnel — recherche et trajectoire quant

## Principes méthodologiques

Le cockpit doit distinguer trois objets qui n'ont pas le même statut :

1. **Observation** — mesure ou événement accompagné d'une source, d'un
   millésime et d'une géolocalisation.
2. **Estimation** — agrégat statistique accompagné d'une couverture, d'une
   incertitude et d'une version de modèle.
3. **Scénario** — choc conditionnel, jamais présenté comme une prévision.

La Banque mondiale insiste sur les marges d'erreur de ses indicateurs WGI et
sur le danger des comparaisons de court terme. Cette discipline est reprise
dans `WM-IQ` : pas d'imputation décorative, score manquant si la couverture est
insuffisante, et intervalle plus large lorsque les observations vieillissent.

INFORM Risk structure le risque autour de `hazard & exposure`, `vulnerability`
et `lack of coping capacity`, combinés de façon multiplicative. Le modèle
WorldMonitor conserve cette séparation conceptuelle, mais utilise actuellement
une moyenne pondérée percentile pour rester interprétable avec le snapshot WDI.
Une version multiplicative ne doit être activée qu'après intégration complète
des dimensions INFORM et validation hors échantillon.

Références primaires :

- [World Bank — WGI 2025 et méthodologie](https://www.worldbank.org/en/publication/worldwide-governance-indicators)
- [World Bank — Indicators API V2](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392)
- [JRC/European Commission — INFORM Risk methodology](https://drmkc.jrc.ec.europa.eu/inform-index/INFORM-Risk/Methodology)

## Moteur quant livré

### Risque structurel pays

Pour chaque indicateur, `WM-IQ 1.0` calcule un percentile transversal à rang
moyen. Le sens de risque est déclaré dans le modèle (`high`, `low`, ou écart à
une cible pour l'inflation). Les facteurs observés sont agrégés à l'intérieur
de quatre piliers, puis les poids des piliers sont réduits proportionnellement
à leur couverture.

La confiance dépend uniquement de deux éléments observables : part du poids de
modèle couverte et fraîcheur des millésimes. La dispersion des facteurs n'est
pas faussement assimilée à un accord entre sources.

### Intensité événementielle

Les primitives prêtes à être utilisées par tous les providers sont :

- décroissance exponentielle par demi-vie propre au type d'événement ;
- corroboration indépendante `1 - produit(1 - fiabilité_source)` ;
- contagion spatiale exponentielle par distance ;
- propagation multi-étapes sur graphe dirigé énergie/commerce/finance.

La prochaine agrégation live doit produire, pour chaque pays et fenêtre :

`intensité = somme(sévérité × confiance × corroboration × décroissance)`

Le score structurel et cette intensité doivent rester deux axes visibles ; les
fusionner trop tôt détruirait l'information entre vulnérabilité et choc.

## Sources institutionnelles prioritaires

### Conflit, humanitaire et catastrophes

- UCDP GED et Candidate : événements de violence géocodés, version annuelle et
  cadence mensuelle Candidate. [API UCDP](https://ucdp.uu.se/apidocs/)
- UNHCR : près de 70 ans de statistiques de déplacement, via API REST.
  [API UNHCR](https://api.unhcr.org/docs/refugee-statistics.html)
- ReliefWeb/OCHA : archive curatée continue ; API V2, `appname` approuvé et
  quotas documentés. [API ReliefWeb](https://apidoc.reliefweb.int/)
- Copernicus EMS : activations, zones d'intérêt, produits raster/vectoriels et
  couches ArcGIS. [API CEMS](https://mapping.emergency.copernicus.eu/about/how-to-harvest-cems-mapping-data/)
- NASA FIRMS : détections NRT ; une requête mondiale VIIRS peut dépasser des
  dizaines de milliers de points, ce qui justifie l'agrégation spatiale.
  [API FIRMS](https://firms.modaps.eosdis.nasa.gov/api/area/)

### Macro, souverain, finance et transmission

- IMF Data/WEO via SDMX pour croissance, inflation, comptes externes et
  projections versionnées. [API IMF](https://data.imf.org/en/Resource-Pages/IMF-API)
- BIS SDMX pour crédit transfrontalier, dette, liquidité et positions bancaires.
  [API BIS](https://stats.bis.org/api-doc/v1/)
- EIA V2 pour énergie internationale et scénarios, avec clé gratuite.
  [API EIA](https://www.eia.gov/opendata/documentation.php)
- UN Comtrade pour reconstruire des graphes bilatéraux produit-pays, calculer
  centralité, concentration de fournisseur et propagation par intrants.

### Sanctions, cyber et espace

- OFAC SLS : listes machine-readable, deltas, programmes et contrôle de hash.
  [OFAC SLS](https://ofac.treasury.gov/sanctions-list-service)
- CISA KEV : catalogue autoritatif des vulnérabilités exploitées dans la nature,
  à croiser avec la présence sectorielle et non à géocoder arbitrairement.
  [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog)
- NOAA SWPC : Kp, vent solaire, événements et prévisions JSON pour risque GNSS,
  satellite, aviation polaire et réseau électrique.
  [NOAA SWPC JSON](https://services.swpc.noaa.gov/json/)

## Axes avancés à haute valeur analytique

### 1. Couche épistémique

Afficher la fraîcheur, le nombre de sources indépendantes, la résolution
spatiale, la révision et les conflits de sources. Une zone très médiatisée ne
doit pas paraître mécaniquement plus risquée qu'une zone peu couverte.

### 2. Graphe de dépendance multi-réseaux

Construire des arêtes pays-pays et actif-actif pour pétrole, LNG, électricité,
minerais, semi-conducteurs, céréales, câbles, transport maritime, commerce et
banques. Mesures : centralité, dépendance au principal fournisseur, entropie,
redondance, capacité de substitution et temps de contournement.

### 3. Water–energy–food nexus

Croiser réservoirs, sécheresse, production hydroélectrique, irrigation,
fertilisants, corridors céréaliers et prix alimentaires. C'est un meilleur
signal de second ordre pour troubles sociaux et inflation que chacune de ces
couches isolée.

### 4. Espace–GNSS–infrastructure

Relier Kp/particules solaires aux routes polaires, navigation GNSS, satellites,
réseaux électriques et pipelines. Séparer brouillage intentionnel et météo
spatiale évite des diagnostics causaux erronés.

### 5. Sanctions en graphe de propriété

Ne pas compter seulement les entités listées : relier alias, propriétaires,
navires, avions, adresses, programmes et juridictions. Calculer exposition
directe, secondaire et risque de contournement, avec règles juridiques
versionnées et validation humaine.

### 6. Validation institutionnelle

Conserver les vintages, interdire le look-ahead, backtester la détection avant
crises avec PR-AUC/Brier score, mesurer dérive et stabilité des rangs, publier
les faux positifs par région et mettre en place un journal des changements de
poids. Le résultat doit être une aide à l'analyse, jamais un signal de trading
opaque.

## Ordre d'intégration recommandé

1. UCDP + UNHCR + ReliefWeb + Copernicus : densité événementielle et impact
   humain sourcés.
2. IMF + BIS + EIA : bilan macro/énergie et canaux de transmission.
3. UN Comtrade : graphe de dépendance et scénarios de chokepoint.
4. OFAC + UE/ONU : graphe de sanctions multi-juridictions.
5. CISA + NOAA SWPC : risques cyber/space-weather correctement séparés.
6. Backtest vintage-aware, calibration et gouvernance du modèle avant toute
   augmentation de complexité statistique.


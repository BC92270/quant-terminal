# Backtest Lab universel

Le moteur universel est un noyau de recherche multi-instruments, multi-actifs et
multi-devises. Il complète le moteur historique sans le remplacer. Le ledger
d’exécution reste la source autoritaire des rendements, coûts, positions et
mouvements de cash.

## Contrat causal

- Tous les timestamps sont convertis en UTC à partir d’une timezone source
  explicite.
- Une cible observée ou rendue disponible à `t` ne peut être exécutée que sur
  une barre strictement postérieure à `t`.
- `event_time` et `target_available_at` sont distincts.
- Une modification de cible en fin d’échantillon sans barre exécutable rend le
  run partiel.
- Les événements de même horloge sont ordonnés par priorité, source, séquence
  source et identifiant déterministe.

## Format CSV long

Champs minimaux :

```text
timestamp,symbol,instrument_id,asset_class,quote_currency,
open,high,low,close
```

Champs d’exécution recommandés :

```text
volume,exchange,multiplier,lot_size,tick_size,settlement_days,
target_weight,target_available_at,fx_to_base,cash_rate_annual
```

Champs dérivés et cycle de vie :

```text
root_symbol,expiry,roll_to,underlying_symbol,strike,option_right,
settlement_type,settlement_price,initial_margin_rate,
maintenance_margin_rate,funding_rate,rollover_rate,borrow_rate,gas_fee,
split,dividend,dividend_payable_at,spinoff_ratio,spinoff_instrument_id,
rights_ratio,rights_instrument_id,merger_cash,symbol_change_to,delisted
```

Le modèle CSV téléchargeable depuis le cockpit contient deux instruments, deux
devises, les taux FX, les taux cash et des cibles causales.

## Couverture native

| Domaine | Traitement |
|---|---|
| Actions et ETF | règlement, splits, dividendes avec payable date, borrow, delisting |
| Crypto spot | cash, frais, gaz et contraintes de volume |
| Crypto perpétuelle | funding, variation de marge et liquidation |
| FX / CFD | P&L en devise de cotation, rollover et conversion historique |
| Futures | multiplier, tick/lot, marge initiale/maintenance, variation margin et roll explicite |
| Options | prime, marge short explicite, règlement cash intrinsèque ou officiel |
| Cash multi-devises | soldes réglés/non réglés, FX PIT, staleness maximale et taux cash historiques |
| Exécution | spread, slippage, impact, participation agrégée et bande de non-intervention |
| Cycle de vie | splits, dividendes, spin-offs, droits, fusions cash et changements d’identifiant explicites |
| OMS autonome | ordres market/limit/stop/stop-limit, GTC/IOC/FOK/DAY, amend/cancel, fills partiels et priorité prix-temps L1 |

Les événements de cycle de vie ne sont comptabilisés que si leurs champs et les
marks contemporains requis sont présents. Les assignments/exercices physiques
et restructurations complexes restent fermés tant qu’un adaptateur spécialisé
et ses données point-in-time ne sont pas fournis. Le noyau OMS autonome est une
fondation testée mais n’est pas encore la voie d’exécution autoritaire du moteur
de poids cibles.

## Strategy Studio et code de stratégie

Le code est le point d’entrée principal du Backtest Lab. Six runtimes sont
supportés par le même contrat fonctionnel : Python 3, JavaScript, TypeScript,
C++20, Rust et C#. Chaque langage expose `initialize` et `on_slice`/`onSlice`
pour recevoir en une fois tous les instruments ayant les mêmes horloges
économique et de disponibilité. Le callback historique `on_bar`/`onBar` reste
compatible. L’historique est limité aux observations déjà reçues ; paramètres
numériques, état persistant et primitive `target_percent` sont communs.

L’éditeur et le processus Streamlit ne chargent jamais le source. Le contrôleur
envoie le code au conteneur par `stdin`, sans volume, sans secret et sans réseau.
Le contrôleur conserve le dataset complet et ne transmet qu’une slice déjà
disponible à la fois. Toutes les barres simultanées sont ajoutées aux historiques
avant le callback, ce qui supprime la dépendance à l’ordre alphabétique des
symboles. Il attend la réponse de la stratégie avant de transmettre la slice
suivante. Le conteneur peut produire uniquement des expositions cibles et des
logs ; il ne calcule jamais les ordres, fills, positions, cash, marge ou P&L.

Le runner impose notamment :

- image identifiée par son `sha256`, `--pull=never` ;
- `--network=none`, `--ipc=none`, aucune capability ;
- root filesystem en lecture seule et unique `tmpfs` borné pour compiler ;
- UID/GID `65532:65532`, `no-new-privileges` ;
- plafonds CPU, mémoire, swap, PID, taille de fichier, output et wall clock ;
- validation stricte du protocole, des symboles et des expositions ;
- signature Ed25519 côté contrôleur, dont la clé privée n’entre jamais dans le
  conteneur.

La politique statique multi-langage est une défense supplémentaire et non la
frontière de sécurité. Sans image Docker immuable et attestation vérifiée, le
run échoue fermé avec `SANDBOX REQUIRED`.

Construction dans le checkout live :

```bash
docker build \
  --file backtest_sandbox/runtime/Dockerfile \
  --tag quant-terminal/backtest-sandbox:2.0.0 \
  backtest_sandbox/runtime
```

Le workflow visible est `Studio → Runs → Compare → Validation → Evidence`.
`Compare` est descriptif : l’autorisation de recherche exige toujours un
protocole purgé hors-échantillon et une correction du multiple testing.

## Gate institutionnel

Un run ne peut atteindre `RESEARCH APPROVED` que si toutes les preuves sont
présentes :

1. snapshot point-in-time signé ;
2. causalité et complétion des cibles ;
3. calendrier de marché authentifié ;
4. réconciliation cash + positions = NAV ;
5. marge, règlement, taux cash et cycle de vie disponibles ;
6. coûts et impact calibrés pour l’instrument/venue ;
7. validation purgée hors-échantillon, correction de tests multiples et
   scénarios ;
8. sandbox attesté lorsque la stratégie provient de code.

La production et la promotion automatique restent toujours désactivées.

## Limites assumées

- La voie autoritaire par poids cibles reste en résolution bar-event. Le noyau
  OMS L1 séparé modélise la liquidité visible et la priorité prix-temps, mais ne
  constitue pas encore un rejeu L2/L3 de carnet ni la voie d’exécution du ledger.
- Les calendriers exchange complets et les données point-in-time licenciées
  doivent provenir d’adaptateurs externes authentifiés.
- Les options à règlement physique et la marge portefeuille broker/clearing
  nécessitent un modèle dédié.
- Le calcul monétaire utilise actuellement des flottants avec réconciliation et
  tolérance stricte ; une comptabilité en unités monétaires entières reste la
  cible pour un déploiement de clearing.

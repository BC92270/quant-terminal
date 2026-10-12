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
split,dividend,dividend_payable_at,delisted
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

Les spin-offs, droits, fusions, changements d’identifiant et assignments
physiques sont détectés mais restent fermés tant qu’un adaptateur spécialisé et
ses données point-in-time ne sont pas fournis.

## Code de stratégie

L’éditeur effectue uniquement une validation statique et calcule l’empreinte du
source. Aucun code utilisateur n’est exécuté dans Streamlit ou dans le processus
hôte.

L’exécution demande un runner OCI séparé attestant au minimum : image immuable,
réseau coupé, filesystem racine en lecture seule, aucun secret monté,
utilisateur non-root et résultat signé. Sans ces preuves, l’état reste
`SANDBOX REQUIRED`.

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

- Résolution événementielle sur les observations fournies, sans rejeu natif de
  carnet d’ordres ni priorité de queue.
- Les calendriers exchange complets et les données point-in-time licenciées
  doivent provenir d’adaptateurs externes authentifiés.
- Les options à règlement physique et la marge portefeuille broker/clearing
  nécessitent un modèle dédié.
- Le calcul monétaire utilise actuellement des flottants avec réconciliation et
  tolérance stricte ; une comptabilité en unités monétaires entières reste la
  cible pour un déploiement de clearing.

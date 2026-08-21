# Security Master

## Objectif

Le routeur institutionnel sépare désormais trois responsabilités qui ne doivent
pas être confondues :

1. l'identité de l'instrument et ses identifiants de référence ;
2. le symbole propre à chaque fournisseur ;
3. la disponibilité effective des prix, fondamentaux et événements.

`institutional_catalog.py` reste le seed éditorial à haute confiance.
`security_master.py` stocke les enregistrements fournisseur dans
`.quant_data/security_master.sqlite3`, puis fusionne les identités par symbole
de routage. Cette base est un cache d'exécution ignoré par Git.

## Sources retenues

| Source | Fonction | État |
| --- | --- | --- |
| SEC EDGAR | Ticker, CIK, raison sociale et bourse des émetteurs américains | Active |
| OpenFIGI v3 | FIGI et symbologie mondiale | Adaptateur prêt |
| Databento | Prix institutionnels et futures mappés | Déjà actif si configuré |
| Twelve Data | Prix FX, actions et ETF | Déjà actif si configuré |
| Yahoo Finance | Fallback best-effort | Actif |
| Frankfurter v2 | Taux FX de référence issus de banques centrales | Adaptateur prévu |
| CoinGecko | Identité et données de marché crypto | Roadmap, clé requise |
| Finnhub / FMP | Événements, news et fondamentaux | Roadmap |

Le dépôt `public-apis/public-apis` est utilisé comme annuaire de découverte,
jamais comme dépendance d'exécution ou preuve de disponibilité. Chaque source
retenue doit être validée contre sa documentation officielle.

Références :

- [SEC ticker and exchange associations](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [OpenFIGI API v3](https://www.openfigi.com/api/documentation)
- [Frankfurter v2](https://frankfurter.dev/)
- [CoinGecko API](https://docs.coingecko.com/reference/coins-markets)

## Synchronisation

Au premier affichage, le routeur initialise le seed local puis tente une
synchronisation SEC si le cache est absent ou vieux de plus de 24 heures. Un
échec réseau ne casse jamais le routeur : il conserve le seed et attend 15
minutes avant une nouvelle tentative automatique.

Synchronisation manuelle :

```bash
python scripts/sync_security_master.py
```

Le bouton `SYNC SOURCES` force la même opération depuis le terminal.

La SEC demande aux clients automatisés de s'identifier. Configurer une valeur
réelle dans l'environnement :

```bash
export SEC_USER_AGENT="YourCompany your.email@example.com"
```

Voir `.env.security-master.example` pour les autres clés.

## Garanties

- SQLite WAL et contrôle d'intégrité.
- Remplacement atomique des données d'une source.
- Historique des synchronisations et erreurs bornées.
- Déduplication déterministe entre seed, SEC et OpenFIGI.
- Priorité au nom, aux tags et au contexte du catalogue éditorial.
- Export du périmètre filtré avec source, bourse, devise et identifiant.
- Aucune clé stockée en base ou rendue dans l'interface.

## Limites assumées

La présence d'un instrument dans la couche de référence ne garantit pas qu'un
fournisseur de prix couvre chaque intervalle demandé. Le routeur expose donc la
provenance et conserve les diagnostics des moteurs de marché. Les obligations
OTC, swaps, CDS et dérivés listés demandent encore des mappings OpenFIGI et des
datasets licenciés avant d'être déclarés routables.

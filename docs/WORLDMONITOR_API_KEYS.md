# WorldMonitor — secrets et connecteurs

## Nécessaires pour déverrouiller les adaptateurs déjà présents

- `ACLED_ACCESS_TOKEN`, ou le couple `ACLED_EMAIL` + `ACLED_PASSWORD` ;
- `OPENSKY_CLIENT_ID` + `OPENSKY_CLIENT_SECRET` ;
- `NEWSAPI_KEY` ;
- `NASA_FIRMS_MAP_KEY`.

`ACLED_KEY` reste accepté comme alias de compatibilité. Les anciens identifiants
OpenSky username/password ne déverrouillent pas le nouvel adaptateur OAuth2 :
il faut bien le couple client ID/client secret.

## Extensions institutionnelles prioritaires

- `COMTRADE_API_KEY` : quotas supérieurs pour le graphe commercial ;
- `EIA_API_KEY` : séries énergie et scénarios ;
- `RELIEFWEB_APPNAME` : identifiant d'application approuvé par ReliefWeb ;
- `GIE_API_KEY` : stockage gaz/LNG européen ;
- `ENTSOE_TOKEN` : flux, production et interconnexions électriques ;
- `WINDY_API_KEY`, `OPENAQ_API_KEY` ou `WAQI_API_KEY` : météo et qualité de
  l'air si ces couches sont activées.

## Sources prioritaires sans clé obligatoire

World Bank Indicators, UCDP, UNHCR Refugee Statistics, IMF SDMX, BIS SDMX,
USGS, GDACS, NASA EONET, OFAC Sanctions List Service, CISA KEV, NOAA SWPC et les
produits publics Copernicus EMS peuvent être intégrés sans secret utilisateur.

Les valeurs des secrets ne doivent jamais être copiées dans le code, le HTML
de la carte ou un export Country Intelligence.

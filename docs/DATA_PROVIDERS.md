# Data providers and API-key audit

## Principle

`public-apis/public-apis` is a discovery catalogue. It contains links and auth
requirements, not reusable credentials. Quant Terminal therefore never
hard-codes a key from that repository. Credentials are resolved from
`.streamlit/secrets.toml` first, then from environment variables, and no audit
prints their values.

Run the non-sensitive local audit with:

```bash
python scripts/audit_data_providers.py
python scripts/audit_data_providers.py --json
```

Use `.env.providers.example` as the canonical list of optional variables.

## Routed-section coverage

| Section | Active order / source | Optional credentials | Explicit fallback | Result of this audit |
| --- | --- | --- | --- | --- |
| Asset Router, FX, commodities, rates | Databento, Twelve Data | `DATABENTO_API_KEY`, `TWELVE_DATA_API_KEY` | Yahoo | Already connected; retained |
| Terminal OHLCV, Momentum / Trend | Twelve Data, Alpha Vantage | `TWELVE_DATA_API_KEY`, `ALPHA_VANTAGE_API_KEY` | Frankfurter for FX, CoinGecko for mapped crypto, then Yahoo | New shared gateway and visible provenance |
| Options | ThetaData, Massive, Tradier | `THETADATA_API_KEY`, `MASSIVE_API_KEY`, `TRADIER_API_TOKEN` | Yahoo public chain | Tradier added; environment-key resolution fixed |
| Futures curve | Massive futures snapshot | `MASSIVE_API_KEY` | Explicit Yahoo contract curve | Existing licensed-first path retained |
| Correlation | App market history plus FRED dependency layer | Market keys, `FRED_API_KEY` | Yahoo and public FRED CSV | Covered; internal peer backfill remains Yahoo |
| Portfolio | Yahoo prices plus OpenFIGI symbology | `OPENFIGI_API_KEY` | Local symbols / Yahoo | Existing path retained |
| Risk, Backtest, Monte Carlo, Decision Engine | Shared app OHLCV for routed instrument | Market keys | Asset-specific keyless source, then Yahoo | Main routed series upgraded; internal benchmarks keep their disclosed fallbacks |
| Company Intelligence | FMP, Alpha Vantage, Finnhub, SEC | `FMP_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `SEC_USER_AGENT` | SEC/Yahoo best effort | Already multi-provider |
| Macro / Central Banks | Official releases, Trading Economics, FRED | `TRADING_ECONOMICS_API_KEY`, `FRED_API_KEY` | Public central-bank archives | Already connected |
| Fixed Income & Credit | FRED, SEC, OpenFIGI | `FRED_API_KEY`, `SEC_USER_AGENT`, `OPENFIGI_API_KEY` | Public FRED CSV and official datasets | Already connected |
| Market Psychology | Twelve Data, Massive, FMP, Alpha Vantage, Finnhub, NewsAPI, FRED, FINRA | Corresponding variables | Yahoo and public event/news feeds | Already has a provider cascade |
| WorldMonitor | ACLED, OpenSky, NASA FIRMS, NewsAPI plus official feeds | See `.env.providers.example` | GDELT, World Bank, USGS, GDACS, NASA EONET and other public sources | Existing provider catalogue retained |
| Security Master | Nasdaq directory, SEC, OpenFIGI | `SEC_USER_AGENT`, `OPENFIGI_API_KEY` | Curated institutional seed | Already connected |
| Quant AI | Session-scoped user-selected model | Entered in the Quant AI session | Deterministic analytics | Intentionally not persisted globally |

## Shared historical-data gateway

The terminal's primary `get_price_history` now uses one deterministic policy:

1. Twelve Data when its key is configured.
2. Alpha Vantage when its key is configured.
3. Frankfurter v2 for ISO FX pairs such as `EURUSD=X`.
4. CoinGecko for explicitly mapped crypto routes such as `BTC-USD`.
5. Yahoo Finance as the final public best-effort fallback.

Every successful frame carries a non-sensitive `data_context` with provider,
status, recency, attempted providers and fallback state. Momentum / Trend shows
that context rather than implying that delayed or reference observations are
real-time. Frankfurter and CoinGecko daily-close series synthesize OHLC fields
for compatibility and are labelled as reference data, not executable quotes.

## Options and futures

Tradier uses the documented production endpoint by default. Set
`TRADIER_ENV=sandbox` only for a sandbox token. Sandbox market data is delayed;
production recency depends on the account entitlement. Tradier's courtesy
Greeks/IV are preserved as vendor fields and identified as ORATS-derived.

ThetaData remains first because its current adapter exposes consolidated OPRA
snapshots. Massive remains second and is still the only licensed futures-curve
adapter in this workspace. Tradier improves US equity-option coverage but does
not replace a futures market-data venue.

## Sources evaluated

- Public APIs catalogue: <https://github.com/public-apis/public-apis>
- Tradier option chains: <https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains>
- Tradier expirations: <https://docs.tradier.com/reference/brokerage-api-markets-get-options-expirations>
- Tradier environments and market-data caveats: <https://docs.tradier.com/docs/endpoints>
- Twelve Data documentation: <https://twelvedata.com/docs>
- Alpha Vantage documentation: <https://www.alphavantage.co/documentation/>
- Frankfurter API: <https://frankfurter.dev/>
- FRED observations API: <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- CoinGecko markets API: <https://docs.coingecko.com/reference/coins-markets>

The catalogue was used to find candidates. Provider-specific official
documentation remains authoritative for endpoints, authentication, rate limits
and entitlements.

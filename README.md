# IFC—PubCo Monitoring

This repository contains a Playwright-powered scraper for capturing TradingView bond ladder data for a list of public company tickers. The script records the stock price and key bond metrics (YTM, price, volume, coupon, maturity, etc.) for each company and stores the results in timestamped CSV snapshots.

## Quick start

1. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   python -m playwright install
   ```

2. (First run) Authenticate to TradingView so the scraper can reuse your session cookies:

   ```bash
   python scrape_bonds.py --login
   ```

   A browser window opens; sign in to TradingView and then return to the terminal to continue.

3. Run the scraper headlessly using a watchlist CSV (defaults to `bond_watchlist.csv`) and write the output to the `output/` directory:

   ```bash
   python scrape_bonds.py --watchlist bond_watchlist.csv --outdir output
   ```

   Use `--headed` and optionally `--slowmo 50` while debugging interactions.

## Watchlist format

Provide a CSV file with at least the following headers:

| Company | Ticker | BondsURL |
|---------|--------|----------|
| Example Homebuilder | EXMPL | https://www.tradingview.com/symbols/BOND-EXMPL/ |

The scraper writes results to `output/bonds_snapshot_<YYYY-MM-DD>.csv` with columns:

```
Ticker, Stock_Price, Bond_Symbol, YTM_pct, Price_pct, Volume, Coupon_pct,
Maturity_Date, Outstanding_Amt, Face_Value, Min_Denom_Amt, Issuer, Source_URL
```

## Authentication state

Successful login saves TradingView cookies to `tv_storage_state.json`, which subsequent runs reuse to avoid repeated logins.
